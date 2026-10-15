// Plain .NET launcher; no embedded program archive, extraction, updater or elevation.
// GPL-3.0. See LICENSE. Author: private0516.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("Mesh Converter")]
[assembly: AssemblyDescription("Transparent Python application launcher")]
[assembly: AssemblyCompany("private0516")]
[assembly: AssemblyProduct("Mesh Converter ALPHA 1.0")]
[assembly: AssemblyCopyright("private0516")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]
[assembly: AssemblyInformationalVersion("ALPHA 1.0")]

internal static class Launcher
{
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AttachConsole(uint processId);
    private static readonly object LogLock = new object();
    private static string logPath;
    private static bool cli;

    private static void Log(string text, bool error = false)
    {
        if (text == null) return;
        lock (LogLock)
        {
            try { if (logPath != null) File.AppendAllText(logPath, text + Environment.NewLine, Encoding.UTF8); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            if (cli)
            {
                try { if (error) Console.Error.WriteLine(text); else Console.Out.WriteLine(text); }
                catch (IOException) { }
            }
        }
    }

    // Windows CommandLineToArgvW quoting, including trailing backslashes.
    private static string Quote(string value)
    {
        StringBuilder result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in value)
        {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') result.Append('\\', slashes * 2 + 1);
            else result.Append('\\', slashes);
            result.Append(c);
            slashes = 0;
        }
        result.Append('\\', slashes * 2);
        return result.Append('"').ToString();
    }

    [STAThread]
    private static int Main(string[] args)
    {
        cli = args.Length > 0;
        if (cli) AttachConsole(0xffffffff);
        try
        {
            string appData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string logDirectory = Path.Combine(appData, "private0516", "MeshConverter", "logs");
            Directory.CreateDirectory(logDirectory);
            logPath = Path.Combine(logDirectory, "launcher-" + DateTime.UtcNow.ToString("yyyyMMdd-HHmmss-fff") + "-" + Process.GetCurrentProcess().Id + ".log");
            if (args.Length > 0 && (args[0] == "--help" || args[0] == "-h"))
            {
                Log("Mesh Converter ALPHA 1.0 / private0516");
                Log("No arguments: open the desktop UI.");
                Log("--cli [arguments]       Run the batch converter; use --cli --help.");
                Log("--inventory [arguments] Run the read-only corpus inventory.");
                Log("--validate [arguments]  Run the isolated sample validation tool.");
                Log("--self-test PATH        Run the application's integration self-test.");
                Log("Other arguments are forwarded unchanged to app/app.py.");
                Log("Logs: " + logDirectory);
                return 0;
            }
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string python = Path.Combine(root, "runtime", "python.exe");
            string scriptName = "app.py";
            int skip = 0;
            if (args.Length > 0)
            {
                if (args[0] == "--cli") { scriptName = "batch_nif.py"; skip = 1; }
                if (args[0] == "--inventory") { scriptName = "corpus_inventory.py"; skip = 1; }
                if (args[0] == "--validate") { scriptName = "validate_samples.py"; skip = 1; }
            }
            string script = Path.Combine(root, "app", scriptName);
            if (!File.Exists(python) || !File.Exists(script))
                throw new FileNotFoundException("The program folder is incomplete. Keep MeshConverter.exe together with app, runtime and vendor folders.");
            List<string> arguments = new List<string>();
            arguments.Add("-B");
            arguments.Add("-X");
            arguments.Add("utf8");
            arguments.Add(script);
            for (int i = skip; i < args.Length; i++) arguments.Add(args[i]);
            string commandLine = String.Join(" ", arguments.ConvertAll(Quote).ToArray());
            Log("Mesh Converter ALPHA 1.0 — transparent folder distribution");
            Log("Runtime: " + python);
            Log("Entry: " + scriptName);
            ProcessStartInfo start = new ProcessStartInfo(python, commandLine);
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WindowStyle = ProcessWindowStyle.Hidden;
            start.RedirectStandardOutput = true;
            start.RedirectStandardError = true;
            start.StandardOutputEncoding = Encoding.UTF8;
            start.StandardErrorEncoding = Encoding.UTF8;
            using (Process process = new Process())
            {
                process.StartInfo = start;
                process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { Log(e.Data); };
                process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { Log(e.Data, true); };
                process.Start();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                process.WaitForExit();
                Log("Process exit code: " + process.ExitCode);
                if (process.ExitCode != 0 && !cli)
                    MessageBox.Show("Mesh Converter could not complete startup.\n\nSee the log for details:\n" + logPath + "\n\nMicrosoft Edge WebView2 Runtime must already be installed.", "Mesh Converter", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return process.ExitCode;
            }
        }
        catch (Exception error)
        {
            Log(error.ToString(), true);
            if (!cli) MessageBox.Show(error.Message + "\n\nLog: " + (logPath ?? "unavailable"), "Mesh Converter", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
