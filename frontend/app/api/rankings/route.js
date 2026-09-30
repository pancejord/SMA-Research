// File purpose: Run the read-only Python ranking query on the server, keeping credentials private.
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { promisify } from "node:util";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const execute = promisify(execFile);

// Return uncached JSON so changing the date window always triggers a fresh report.
function respond(body, status = 200) {
  return Response.json(body, { status, headers: { "Cache-Control": "no-store" } });
}

// Validate browser input and call the existing Python reporting logic without a shell.
export async function GET(request) {
  const params = new URL(request.url).searchParams;
  const options = {
    days: Number(params.get("days") ?? 5),
    top: Number(params.get("top") ?? 25),
    ticker: (params.get("ticker") ?? "").trim().toUpperCase(),
    timeframe: params.get("timeframe") ?? "",
    through: params.get("through") ?? "",
  };
  if (!Number.isInteger(options.days) || options.days < 2 || options.days > 20 ||
      !Number.isInteger(options.top) || options.top < 1 || options.top > 100 ||
      !/^[A-Z0-9.:_-]{0,30}$/.test(options.ticker) ||
      !/^(?:[5-9]m|[1-5][0-9]m|[1-4]h)?$/.test(options.timeframe) ||
      (options.through && !/^\d{4}-\d{2}-\d{2}$/.test(options.through))) {
    return respond({ error: "Choose 2–20 trading days and valid filters." }, 400);
  }

  const frontend = process.cwd();
  const project = path.resolve(frontend, "..");
  const localPython = path.join(project, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  const python = process.env.PYTHON_EXECUTABLE || (existsSync(localPython) ? localPython : process.platform === "win32" ? "python" : "python3");
  try {
    const { stdout } = await execute(python, [path.join(frontend, "rankings_bridge.py"), JSON.stringify(options)], {
      cwd: project, timeout: 45000, maxBuffer: 1024 * 1024, windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    });
    const report = JSON.parse(stdout);
    return respond(report, report.error ? (report.kind === "invalid" ? 400 : 503) : 200);
  } catch (error) {
    // Never expose raw subprocess output, paths, or database error bodies to the browser.
    const message = error.code === "ENOENT"
      ? "Python was not found. Set PYTHON_EXECUTABLE in frontend/.env.local."
      : error.killed
        ? "The report timed out. Check the database connection and try again."
        : "The reporting service could not start. Check Python dependencies and server configuration.";
    return respond({ error: message }, 503);
  }
}
