"""Deterministic synthetic world for a foodservice distributor with its own refrigerated fleet.

Every branch, customer, driver, truck, place and figure here is made up. The generator is seeded per
entity (route and day, customer, truck), so the mock APIs and the ERP seed build identical records in
separate processes without sharing state.

The behaviour the warehouse has to cope with is built in on purpose:

* Drivers who fall behind often skip the "delivered" tap and type an in-window time at the end of the
  shift, so the TMS overstates on-time delivery. The telematics geofence arrival is the trustworthy time.
* TMS windows and delivered times are branch local time with no offset; telematics is UTC.
* Short and refused cases are credited on separate negative invoices one to five days later.
* Some customers move between branches (route rebalancing), so the customer dimension needs history.
* One truck's telematics unit drops most geofence events for part of the year.
* A handful of geofence arrivals carry a GPS clock glitch that puts them before the route was dispatched.
"""

from __future__ import annotations

import hashlib
import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from functools import cached_property
from zoneinfo import ZoneInfo

SEED = 7
HISTORY_START = date(2025, 10, 1)
AS_OF = date(2026, 10, 30)
HORIZON_DAYS = 45  # how far past AS_OF the world is generated, for `fleetbi advance`
UTC = timezone.utc


@dataclass(frozen=True)
class Branch:
    code: str
    name: str
    region: str
    tz_windows: str  # what SQL Server's AT TIME ZONE expects
    tz_iana: str

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_iana)


BRANCHES = [
    Branch("HAL", "Halverton", "Central", "Central Standard Time", "America/Chicago"),
    Branch("ASH", "Ashbury Ridge", "Central", "Central Standard Time", "America/Chicago"),
    Branch("COR", "Corran Flats", "Central", "Central Standard Time", "America/Chicago"),
    Branch("MAR", "Lake Marlow", "Central", "Central Standard Time", "America/Chicago"),
    Branch("RED", "Redstone Mesa", "Mountain", "Mountain Standard Time", "America/Denver"),
    Branch("SIL", "Silver Pines", "Mountain", "Mountain Standard Time", "America/Denver"),
]
BRANCH_BY_CODE = {b.code: b for b in BRANCHES}


@dataclass(frozen=True)
class Category:
    code: str
    name: str
    temp_zone: str
    price_per_case: float
    margin: float


CATEGORIES = [
    Category("PRD", "Produce", "Chilled", 32.0, 0.24),
    Category("DRY", "Dry Goods", "Dry", 30.0, 0.22),
    Category("DAI", "Dairy", "Chilled", 38.0, 0.18),
    Category("MEA", "Meat and Seafood", "Chilled", 95.0, 0.16),
    Category("FRZ", "Frozen", "Frozen", 55.0, 0.21),
    Category("PAP", "Paper and Chemical", "Dry", 42.0, 0.28),
]
SEGMENT_PRICE = {"Restaurant": 1.0, "School": 0.9, "Healthcare": 0.95}

ROUTES_PER_BRANCH = 3
CUSTOMERS_PER_BRANCH = 70

# Delay model, tuned so about 86% of geofence arrivals land inside the window (tests pin the range).
BAD_DAY_PROB = 0.17
FIRST_LEG = (20, 40)
TRAVEL = (10, 20)
DWELL = (10, 22)
DRIFT_STEP = (1.6, 7.6)
BAD_DAY_DELAY = (50, 140)
BACKFILL_IF_LATE = 0.60
BACKFILL_IF_ON_TIME = 0.05
GEOFENCE_MISSING_BASE = 0.02
GEOFENCE_MISSING_FAULTY = 0.28
FAULTY_TRUCK = "T502"  # Redstone Mesa, route RED-02
FAULTY_FROM = date(2026, 8, 17)
ARRIVAL_GLITCH_PROB = 0.002
CORRECTION_PROB = 0.05
SHORT_PROB = 0.06
REFUSED_PROB = 0.025
PICKUP_ORDERS_PER_BRANCH_DAY = 0.4
ORDER_LINK_MISSING_PROB = 0.003
OFF_ROUTE_FUEL_PROB = 0.004

# Customers moved by route rebalancing: (effective date, from route, to route, how many).
MOVES = [
    (date(2026, 3, 2), "HAL-03", "ASH-02", 8),
    (date(2026, 11, 2), "COR-01", "MAR-03", 3),  # in the future at AS_OF; appears after `fleetbi advance`
]

_FIRST = ["Avery", "Blake", "Casey", "Dana", "Elliot", "Frankie", "Gray", "Harper", "Indy", "Jordan", "Kai",
          "Logan", "Morgan", "Noel", "Oakley", "Parker", "Quinn", "Reese", "Sage", "Taylor", "Umi", "Val",
          "Wren", "Yael", "Zion", "Rowan", "Emery", "Finley"]
_LAST = ["Abernathy", "Brightwater", "Calloway", "Dunmore", "Everly", "Fairbank", "Galloway", "Hollis",
         "Ivers", "Jessup", "Kettering", "Lindqvist", "Marchetti", "Northcott", "Okafor", "Pemberton",
         "Quarles", "Ridley", "Stanhope", "Thackeray", "Underhill", "Vasquez", "Whitlock", "Yardley"]
_ADJ = ["Copper", "Juniper", "Harbor", "Saffron", "Blue Heron", "Old Mill", "Cedar", "Golden Fork", "Iron Gate",
        "Lantern", "Maple", "Northfield", "Prairie", "Red Barn", "Silver Spoon", "Three Oaks", "Willow",
        "Stonegate", "Brickyard", "Riverbend"]
_REST = ["Bistro", "Grill", "Kitchen", "Cantina", "Diner", "Tavern", "Trattoria", "Smokehouse", "Cafe",
         "Noodle Bar"]
_SCHOOL = ["Elementary", "Middle School", "High School", "Academy"]
_HEALTH = ["Care Center", "Senior Living", "Medical Center", "Rehab Hospital"]


def rng(*key) -> random.Random:
    return random.Random(f"{SEED}:" + ":".join(str(k) for k in key))


def guid(*key) -> str:
    return str(uuid.UUID(bytes=hashlib.md5(("|".join(str(k) for k in key)).encode()).digest()))


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_local(dt: datetime) -> str:
    return dt.replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")


def local_dt(branch: Branch, d: date, minutes: float) -> datetime:
    """Branch-local wall time `minutes` after midnight on `d`, as an aware datetime."""
    naive = datetime.combine(d, time(0, 0)) + timedelta(minutes=round(minutes))
    return naive.replace(tzinfo=branch.tz)


def default_clock(as_of: date = AS_OF) -> datetime:
    """06:00 UTC the day after AS_OF: every branch has finished the AS_OF routes and shift-end entries."""
    return datetime.combine(as_of + timedelta(days=1), time(6, 0), tzinfo=UTC)


@dataclass
class Truck:
    code: str
    branch: str
    model_year: int
    reefer_type: str


@dataclass
class Driver:
    code: str
    name: str
    branch: str
    hourly_rate: float


@dataclass
class Route:
    code: str
    name: str
    branch: str
    truck: str
    driver: str
    spare_truck: str
    relief_driver: str


@dataclass
class Customer:
    number: str
    name: str
    segment: str
    route0: str  # route before any move
    days: tuple[int, ...]  # weekday numbers, Monday = 0
    window_start: int  # minutes after midnight, local
    window_len: int
    moves: list[tuple[date, str]] = field(default_factory=list)  # (effective date, new route)

    def route_on(self, d: date) -> str:
        r = self.route0
        for eff, new in self.moves:
            if d >= eff:
                r = new
        return r


@dataclass
class Version:
    updated_at: datetime
    payload: dict


@dataclass
class Record:
    id: str
    versions: list[Version]


@dataclass
class Stop:
    id: str
    route_plan_id: str
    route: str
    branch: str
    d: date
    seq: int
    truck: str
    driver: str
    customer: str
    order_number: str
    window_start: datetime
    window_end: datetime
    arrival: datetime  # true arrival (what the geofence saw, unless glitched)
    departure: datetime
    delivered_at: datetime  # what the driver typed, local
    delivered_recorded_at: datetime  # when the TMS recorded the tap or the typed entry
    backfilled: bool
    geofence: bool
    glitch: bool
    ordered: dict[str, int]
    short_cases: int
    refused_cases: int
    correction: tuple[datetime, int, int] | None  # (when, short, refused) after the correction


@dataclass
class RouteDay:
    id: str
    route: str
    branch: str
    d: date
    truck: str
    driver: str
    dispatch_planned: datetime
    dispatch_actual: datetime
    returned: datetime
    planned_miles: float
    driven_miles: float
    idle_minutes: int
    stops: list[Stop]


class World:
    """All synthetic entities between HISTORY_START and AS_OF + HORIZON_DAYS."""

    def __init__(self, start: date = HISTORY_START, as_of: date = AS_OF, branches: list[str] | None = None):
        self.start = start
        self.as_of = as_of
        self.end = as_of + timedelta(days=HORIZON_DAYS)
        codes = branches or [b.code for b in BRANCHES]
        self.branches = [BRANCH_BY_CODE[c] for c in codes]
        self.trucks: dict[str, Truck] = {}
        self.drivers: dict[str, Driver] = {}
        self.routes: dict[str, Route] = {}
        self.customers: dict[str, Customer] = {}
        self._build_masters()

    # ---------------------------------------------------------------- masters
    def _build_masters(self) -> None:
        for bi, b in enumerate(BRANCHES):
            if b not in self.branches:
                continue
            r = rng("branch", b.code)
            trucks = []
            for t in range(ROUTES_PER_BRANCH + 1):
                code = f"T{(bi + 1) * 100 + t + 1}"
                self.trucks[code] = Truck(code, b.code, r.choice([2019, 2020, 2021, 2022, 2023, 2024]),
                                          r.choice(["Single temp", "Multi temp"]))
                trucks.append(code)
            drivers = []
            for t in range(ROUTES_PER_BRANCH + 1):
                code = f"D{(bi + 1) * 1000 + t + 1}"
                self.drivers[code] = Driver(code, f"{r.choice(_FIRST)} {r.choice(_LAST)}", b.code,
                                            round(r.uniform(27.0, 34.0), 2))
                drivers.append(code)
            for n in range(ROUTES_PER_BRANCH):
                code = f"{b.code}-{n + 1:02d}"
                self.routes[code] = Route(code, f"{b.name} {n + 1}", b.code, trucks[n], drivers[n], trucks[-1],
                                          drivers[-1])
            for c in range(CUSTOMERS_PER_BRANCH):
                num = f"C{(bi + 1) * 1000 + c + 1}"
                cr = rng("customer", num)
                seg = cr.choices(["Restaurant", "School", "Healthcare"], [0.6, 0.25, 0.15])[0]
                if seg == "Restaurant":
                    name = f"{cr.choice(_ADJ)} {cr.choice(_REST)}"
                    days = tuple(sorted(cr.sample(range(6), 3)))
                    ws = cr.choice([360, 420, 480, 540])
                    wl = cr.choice([180, 240])
                elif seg == "School":
                    name = f"{cr.choice(_ADJ)} {cr.choice(_SCHOOL)}"
                    days = tuple(sorted(cr.sample(range(5), 2)))
                    ws, wl = cr.choice([330, 360]), cr.choice([150, 180])
                else:
                    name = f"{cr.choice(_ADJ)} {cr.choice(_HEALTH)}"
                    days = tuple(sorted(cr.sample(range(6), 3)))
                    ws, wl = cr.choice([330, 390]), cr.choice([180, 240])
                route = f"{b.code}-{c % ROUTES_PER_BRANCH + 1:02d}"
                self.customers[num] = Customer(num, name, seg, route, days, ws, wl)
        for eff, src, dst, k in MOVES:
            if src not in self.routes or dst not in self.routes:
                continue
            movers = [c for c in self.customers.values() if c.route0 == src and not c.moves][:k]
            for c in movers:
                c.moves.append((eff, dst))

    def customer_branch_history(self) -> list[tuple[str, str, str, date]]:
        """(customer, branch, segment, effective_from) rows, the ERP's assignment history."""
        rows = []
        for c in self.customers.values():
            rows.append((c.number, self.routes[c.route0].branch, c.segment, date(2024, 1, 1)))
            for eff, new in c.moves:
                rows.append((c.number, self.routes[new].branch, c.segment, eff))
        return rows

    # ---------------------------------------------------------------- days
    def operating_days(self, d1: date | None = None, d2: date | None = None):
        d = d1 or self.start
        last = d2 or self.end
        while d <= last:
            if d.weekday() < 6:
                yield d
            d += timedelta(days=1)

    @staticmethod
    def school_closed(d: date) -> bool:
        summer = (6, 12) <= (d.month, d.day) <= (8, 14)
        winter = (d.month == 12 and d.day >= 22) or (d.month == 1 and d.day <= 2)
        return summer or winter

    @cached_property
    def _route_candidates(self) -> dict[str, list[Customer]]:
        out: dict[str, list[Customer]] = {code: [] for code in self.routes}
        for c in self.customers.values():
            for code in {c.route0, *(new for _, new in c.moves)}:
                out[code].append(c)
        return out

    @cached_property
    def route_days(self) -> list[RouteDay]:
        out = []
        for d in self.operating_days():
            for route in self.routes.values():
                rd = self._route_day(route, d)
                if rd:
                    out.append(rd)
        return out

    def _route_day(self, route: Route, d: date) -> RouteDay | None:
        branch = BRANCH_BY_CODE[route.branch]
        custs = [c for c in self._route_candidates[route.code]
                 if c.route_on(d) == route.code and d.weekday() in c.days
                 and not (c.segment == "School" and self.school_closed(d))]
        if not custs:
            return None
        custs.sort(key=lambda c: (c.window_start, c.number))
        r = rng("routeday", route.code, d)
        truck = route.spare_truck if r.random() < 0.03 else route.truck
        driver = route.relief_driver if r.random() < 0.10 else route.driver
        rd_id = guid("routeplan", route.code, d)
        dispatch_planned = local_dt(branch, d, 285)
        dispatch_actual = dispatch_planned + timedelta(minutes=r.gauss(4, 6))
        bad_day = r.random() < BAD_DAY_PROB
        bad_at = r.randrange(len(custs)) if bad_day else -1
        t = dispatch_actual + timedelta(minutes=r.uniform(*FIRST_LEG))
        planned_miles = r.uniform(8, 16)
        drift = 0.0
        earliest = dispatch_actual + timedelta(minutes=FIRST_LEG[0])  # a truck can't beat the drive
        stops: list[Stop] = []
        for i, c in enumerate(custs):
            if i > 0:
                t += timedelta(minutes=r.uniform(*TRAVEL))
            leg = r.uniform(5, 13)
            planned_miles += leg
            drift = max(-15.0, drift + r.gauss(*DRIFT_STEP))
            if i == bad_at:
                drift += r.uniform(*BAD_DAY_DELAY)
            ws = local_dt(branch, d, c.window_start)
            we = ws + timedelta(minutes=c.window_len)
            # Wait for a window that hasn't opened (most customers allow at most 30 minutes early).
            planned_arrival = max(t, ws - timedelta(minutes=30))
            arrival = max(earliest, planned_arrival + timedelta(minutes=drift + r.gauss(0, 12)))
            dwell = r.uniform(*DWELL)
            departure = arrival + timedelta(minutes=dwell)
            earliest = departure + timedelta(minutes=TRAVEL[0])
            t = departure - timedelta(minutes=drift)  # the plan keeps going; drift carries separately
            stops.append(self._stop(route, branch, d, i + 1, truck, driver, c, ws, we, arrival, departure, r, rd_id))
        last_exit = max(s.departure for s in stops)
        returned = last_exit + timedelta(minutes=r.uniform(25, 50))
        # Shift-end entries happen after the truck is back at the branch.
        for s in stops:
            if s.backfilled:
                s.delivered_recorded_at = returned + timedelta(minutes=r.uniform(5, 35))
        driven = planned_miles * r.uniform(0.98, 1.10) + (r.uniform(4, 15) if bad_day else 0)
        return RouteDay(rd_id, route.code, route.branch, d, truck, driver, dispatch_planned, dispatch_actual,
                        returned, round(planned_miles, 1), round(driven, 1), int(r.uniform(10, 55)), stops)

    def _stop(self, route, branch, d, seq, truck, driver, c, ws, we, arrival, departure, r, rd_id) -> Stop:
        late = arrival > we
        backfilled = r.random() < (BACKFILL_IF_LATE if late else BACKFILL_IF_ON_TIME)
        if backfilled:
            delivered = arrival + timedelta(minutes=r.uniform(3, 15)) if not late else \
                we - timedelta(minutes=r.uniform(5, 45))
            recorded = departure  # replaced with the shift end once the route day is known
        else:
            delivered = arrival + timedelta(minutes=r.uniform(1, 8))
            recorded = delivered + timedelta(seconds=r.uniform(2, 40))
        missing_p = GEOFENCE_MISSING_FAULTY if (truck == FAULTY_TRUCK and d >= FAULTY_FROM) else GEOFENCE_MISSING_BASE
        geofence = r.random() >= missing_p
        glitch = geofence and r.random() < ARRIVAL_GLITCH_PROB
        cr = rng("order", c.number, d)
        base = {"Restaurant": (15, 45), "School": (25, 70), "Healthcare": (20, 60)}[c.segment]
        total = cr.randint(*base)
        cats = cr.sample([k.code for k in CATEGORIES], cr.randint(2, 5))
        weights = [cr.random() + 0.2 for _ in cats]
        ordered: dict[str, int] = {}
        left = total
        for i, k in enumerate(cats):
            if i == len(cats) - 1:
                n = left
            else:
                n = max(1, min(round(total * weights[i] / sum(weights)), left - (len(cats) - 1 - i)))
            ordered[k] = n
            left -= n
        short = r.randint(1, 4) if r.random() < SHORT_PROB else 0
        refused = r.randint(1, 3) if r.random() < REFUSED_PROB else 0
        correction = None
        if r.random() < CORRECTION_PROB:
            when = local_dt(branch, d + timedelta(days=r.choice([1, 1, 2])), r.uniform(480, 600))
            if r.random() < 0.6:
                correction = (when, short + 1, refused)
            else:
                correction = (when, max(0, short - 1), refused + 1)
        sid = guid("stop", route.code, d, seq)
        return Stop(sid, rd_id, route.code, branch.code, d, seq, truck, driver, c.number,
                    order_number="", window_start=ws, window_end=we, arrival=arrival, departure=departure,
                    delivered_at=delivered, delivered_recorded_at=recorded, backfilled=backfilled,
                    geofence=geofence, glitch=glitch, ordered=ordered, short_cases=short, refused_cases=refused,
                    correction=correction)

    @cached_property
    def stops(self) -> list[Stop]:
        out = [s for rd in self.route_days for s in rd.stops]
        out.sort(key=lambda s: (s.d, s.route, s.seq))
        for i, s in enumerate(out):
            s.order_number = f"SO{100000 + i}"
        return out

    def final_cases(self, s: Stop) -> tuple[int, int]:
        if s.correction:
            return s.correction[1], s.correction[2]
        return s.short_cases, s.refused_cases

    # ---------------------------------------------------------------- source records (API side)
    def route_plan_records(self) -> list[Record]:
        out = []
        for rd in self.route_days:
            branch = BRANCH_BY_CODE[rd.branch]
            created = local_dt(branch, rd.d - timedelta(days=1), 900)
            route = self.routes[rd.route]
            out.append(Record(rd.id, [Version(created, {
                "id": rd.id, "route_code": rd.route, "route_name": route.name, "branch_code": rd.branch,
                "route_date": rd.d.isoformat(), "truck_code": rd.truck, "driver_code": rd.driver,
                "dispatch_at": iso_local(rd.dispatch_planned), "planned_miles": rd.planned_miles,
                "planned_stops": len(rd.stops), "updated_at": iso_utc(created)})]))
        return out

    def stop_records(self) -> list[Record]:
        _ = self.stops  # assigns order numbers
        out = []
        for rd in self.route_days:
            branch = BRANCH_BY_CODE[rd.branch]
            created = local_dt(branch, rd.d - timedelta(days=1), 900)
            for s in rd.stops:
                base = {
                    "id": s.id, "route_plan_id": s.route_plan_id, "route_code": s.route, "route_date": s.d.isoformat(),
                    "branch_code": s.branch, "truck_code": s.truck, "driver_code": s.driver, "sequence": s.seq,
                    "customer_number": s.customer, "order_number": s.order_number,
                    "window_start": iso_local(s.window_start), "window_end": iso_local(s.window_end),
                    "ordered_cases": sum(s.ordered.values()),
                }
                planned = dict(base, status="planned", delivered_at=None, delivered_recorded_at=None,
                               short_cases=0, refused_cases=0, updated_at=iso_utc(created))
                done = dict(base, status="completed", delivered_at=iso_local(s.delivered_at),
                            delivered_recorded_at=iso_utc(s.delivered_recorded_at), short_cases=s.short_cases,
                            refused_cases=s.refused_cases, updated_at=iso_utc(s.delivered_recorded_at))
                versions = [Version(created, planned), Version(s.delivered_recorded_at, done)]
                if s.correction:
                    when, sh, rf = s.correction
                    versions.append(Version(when, dict(done, short_cases=sh, refused_cases=rf,
                                                       updated_at=iso_utc(when))))
                out.append(Record(s.id, versions))
        return out

    def visit_records(self) -> list[Record]:
        out = []
        for rd in self.route_days:
            for s in rd.stops:
                if not s.geofence:
                    continue
                entered = s.arrival
                if s.glitch:
                    entered = rd.dispatch_actual - timedelta(minutes=rng("glitch", s.id).uniform(10, 90))
                vid = guid("visit", s.id)
                upd = s.departure + timedelta(minutes=2)
                out.append(Record(vid, [Version(upd, {
                    "id": vid, "truck_code": s.truck, "customer_number": s.customer, "entered_at": iso_utc(entered),
                    "exited_at": iso_utc(s.departure), "updated_at": iso_utc(upd)})]))
        return out

    def trip_records(self) -> list[Record]:
        out = []
        for rd in self.route_days:
            tid = guid("trip", rd.truck, rd.d)
            upd = rd.returned + timedelta(minutes=5)
            out.append(Record(tid, [Version(upd, {
                "id": tid, "truck_code": rd.truck, "trip_date": rd.d.isoformat(),
                "started_at": iso_utc(rd.dispatch_actual), "ended_at": iso_utc(rd.returned),
                "miles": rd.driven_miles, "idle_minutes": rd.idle_minutes, "updated_at": iso_utc(upd)})]))
        return out

    # ---------------------------------------------------------------- ERP side
    def unit_price(self, customer: Customer, cat: Category) -> float:
        r = rng("price", customer.number, cat.code)
        return round(cat.price_per_case * SEGMENT_PRICE[customer.segment] * r.uniform(0.94, 1.06), 2)

    def erp_documents(self, d1: date, d2: date):
        """Orders, invoice lines and credit lines whose posting date falls in [d1, d2]."""
        cats = {c.code: c for c in CATEGORIES}
        orders, lines = [], []
        for s in self.stops:
            if not (d1 <= s.d <= d2):
                continue
            cust = self.customers[s.customer]
            link_missing = rng("link", s.id).random() < ORDER_LINK_MISSING_PROB
            orders.append((s.order_number, s.customer, s.d, None if link_missing else s.id, "delivery"))
            inv = "IN" + s.order_number[2:]
            for n, (k, cases) in enumerate(sorted(s.ordered.items()), start=1):
                price = self.unit_price(cust, cats[k])
                rev = round(price * cases, 2)
                lines.append((inv, n, s.order_number, s.customer, s.d, k, cases, rev,
                              round(rev * (1 - cats[k].margin), 2), None))
        # Credits for short and refused cases, posted one to five days after the delivery.
        for s in self.stops:
            short, refused = self.final_cases(s)
            if short + refused == 0:
                continue
            post = s.d + timedelta(days=rng("credit", s.id).randint(1, 5))
            if not (d1 <= post <= d2):
                continue
            cust = self.customers[s.customer]
            left = short + refused
            n = 0
            for k, cases in sorted(s.ordered.items(), key=lambda kv: -kv[1]):
                if left <= 0:
                    break
                take = min(cases, left)
                left -= take
                n += 1
                price = self.unit_price(cust, cats[k])
                rev = round(price * take, 2)
                lines.append(("CR" + s.order_number[2:], n, s.order_number, s.customer, post, k, -take, -rev,
                              -round(rev * (1 - cats[k].margin), 2), "IN" + s.order_number[2:]))
        # Will-call pickups: orders with no stop at all.
        for d in self.operating_days(d1, d2):
            for b in self.branches:
                r = rng("pickup", b.code, d)
                if r.random() < PICKUP_ORDERS_PER_BRANCH_DAY:
                    cust = r.choice([c for c in self.customers.values()
                                     if self.routes[c.route_on(d)].branch == b.code])
                    on = f"PU{d:%y%m%d}{b.code}"
                    orders.append((on, cust.number, d, None, "pickup"))
                    k = r.choice(CATEGORIES)
                    cases = r.randint(2, 8)
                    rev = round(self.unit_price(cust, k) * cases, 2)
                    lines.append(("IN" + on[2:], 1, on, cust.number, d, k.code, cases, rev,
                                  round(rev * (1 - k.margin), 2), None))
        return orders, lines

    # ---------------------------------------------------------------- fuel card files
    def fuel_rows(self, d: date) -> list[dict]:
        rows = []
        by_truck = {rd.truck: rd for rd in self.route_days if rd.d == d}
        for code, truck in sorted(self.trucks.items()):
            r = rng("fuel", code, d)
            branch = BRANCH_BY_CODE[truck.branch]
            rd = by_truck.get(code)
            if rd is not None and r.random() < 0.5:
                when = rd.returned + timedelta(minutes=r.uniform(5, 40))
                gallons = round(rd.driven_miles * 2 / r.uniform(6.8, 8.2), 1)
            elif rd is None and r.random() < OFF_ROUTE_FUEL_PROB:
                when = local_dt(branch, d, r.uniform(600, 900))
                gallons = round(r.uniform(15, 40), 1)
            else:
                continue
            ppg = round(3.85 + 0.22 * math.sin((d.toordinal() % 365) / 58.1) + r.uniform(-0.06, 0.06), 3)
            rows.append({"card_number": f"5550{int(code[1:]):04d}", "truck_code": code,
                         "txn_time_local": iso_local(when), "site_name": f"{branch.name} Fuel Island",
                         "gallons": f"{gallons:.1f}", "price_per_gallon": f"{ppg:.3f}",
                         "amount": f"{gallons * ppg:.2f}"})
        return rows


def latest_visible(records: list[Record], now: datetime, overrides: dict[str, datetime] | None = None):
    """Latest version of each record that exists at `now`, as (updated_at, id, payload) sorted by time then id."""
    out = []
    for rec in records:
        best = None
        for v in rec.versions:
            if v.updated_at <= now and (best is None or v.updated_at >= best.updated_at):
                best = v
        if best is None:
            continue
        # APIs publish whole seconds; order and page on exactly what the client sees.
        upd = best.updated_at.replace(microsecond=0)
        payload = best.payload
        if overrides and rec.id in overrides:
            upd = overrides[rec.id].replace(microsecond=0)
            payload = dict(payload, updated_at=iso_utc(upd))
        out.append((upd.astimezone(UTC), rec.id, payload))
    out.sort(key=lambda t: (t[0], t[1]))
    return out
