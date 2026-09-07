// ---------------------------------------------------------------
// Spotware standard bridge — identical across all Python algo samples.
// Source: spotware/ctrader-python-algo-samples (MIT-licensed).
// DO NOT EDIT — regenerate from Spotware samples if upgrading.
// ---------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Python.Runtime;

namespace cAlgo.Robots;

internal static class EmbeddedResourceProvider
{
    private static List<string> _list;
    private static PythonManifest _pythonManifest;

    public static List<string> List()
    {
        if (_list != null)
            return _list;

        var assembly = typeof(EmbeddedResourceProvider).Assembly;
        _list = assembly.GetManifestResourceNames().ToList();

        return _list;
    }

    public static Stream ReadStream(string resourceName)
    {
        var assembly = typeof(EmbeddedResourceProvider).Assembly;
        return assembly.GetManifestResourceStream(resourceName);
    }

    public static string ReadText(string name)
    {
        var assembly = typeof(EmbeddedResourceProvider).Assembly;
        var resourceName = assembly.GetManifestResourceNames()
            .SingleOrDefault(n => n.EndsWith($".{name}", StringComparison.OrdinalIgnoreCase));

        if (resourceName == null)
            return null;

        using var stream = assembly.GetManifestResourceStream(resourceName);
        if (stream == null)
            return null;

        using var stringReader = new StreamReader(stream);
        return stringReader.ReadToEnd();
    }

    public static bool TryGetPythonManifest(out PythonManifest pythonManifest)
    {
        if (_pythonManifest != null)
        {
            pythonManifest = _pythonManifest;
            return true;
        }

        var manifestResourceName = List().FirstOrDefault(res => res.ToLower().EndsWith("manifest.json"));

        if (string.IsNullOrEmpty(manifestResourceName))
        {
            pythonManifest = null;
            return false;
        }

        using var stream = ReadStream(manifestResourceName);
        using var reader = new StreamReader(stream);
        var json = reader.ReadToEnd();
        pythonManifest = System.Text.Json.JsonSerializer.Deserialize<PythonManifest>(json);
        _pythonManifest = pythonManifest;
        return true;
    }
}
