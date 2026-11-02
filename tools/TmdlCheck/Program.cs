// Loads the TMDL folder with Microsoft's Tabular Object Model (the same library Power BI Desktop and
// Fabric use), fails on any TMDL syntax or reference error, and writes the model as TMSL JSON
// (model.bim) for the Python best-practice checks and the data dictionary.
using Microsoft.AnalysisServices.Tabular;
using Microsoft.AnalysisServices.Tabular.Tmdl;

if (args.Length != 2)
{
    Console.Error.WriteLine("usage: TmdlCheck <definition folder> <output model.bim>");
    return 2;
}

try
{
    var database = TmdlSerializer.DeserializeDatabaseFromFolder(args[0]);
    var model = database.Model;
    var json = JsonSerializer.SerializeDatabase(database, new SerializeOptions
    {
        IgnoreTimestamps = true,
        IgnoreInferredObjects = true,
        IgnoreInferredProperties = true,
    });
    Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(args[1]))!);
    File.WriteAllText(args[1], json);
    Console.WriteLine(
        $"TMDL ok: {model.Tables.Count} tables, {model.Tables.Sum(t => t.Measures.Count)} measures, " +
        $"{model.Relationships.Count} relationships, {model.Roles.Count} roles, " +
        $"{model.Tables.Count(t => t.RefreshPolicy != null)} incremental refresh policies");
    return 0;
}
catch (Exception ex) when (ex is TmdlFormatException or TmdlSerializationException)
{
    Console.Error.WriteLine($"TMDL error: {ex.Message}");
    return 1;
}
