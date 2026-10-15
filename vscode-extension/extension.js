// DepExit VS Code extension: shows the Exit Capsule from the DepExit API inside the editor.
// - Diagnostics on every usage location and manifest line of an at-risk dependency
// - Hover with risk indicators, Gemma 4 proposal and test gaps
// - Quick fix: replace the file with its migrated version (from the Docker-verified workspace)
const vscode = require("vscode");
const cp = require("child_process");

const LEVELS = ["none", "low", "medium", "high", "critical"];
let diagnostics, statusBar, output;
let state = { id: null, capsule: null, byFile: new Map() };

function cfg() {
  const c = vscode.workspace.getConfiguration("depexit");
  return { api: c.get("apiUrl").replace(/\/$/, ""), minLevel: c.get("minLevel") };
}

async function api(path, asText = false, init = {}) {
  const res = await fetch(cfg().api + path, init);
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { msg = (await res.json()).error.message; } catch { /* plain text */ }
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return asText ? res.text() : res.json();
}

function workspaceRoot() {
  const f = vscode.workspace.workspaceFolders;
  return f && f.length ? f[0].uri : null;
}

function gitRemote(root) {
  try {
    const url = cp.execSync("git config --get remote.origin.url", { cwd: root.fsPath }).toString().trim();
    const m = url.match(/github\.com[:/]([^/]+)\/(.+?)(\.git)?$/);
    return m ? `https://github.com/${m[1]}/${m[2]}` : "";
  } catch { return ""; }
}

const severityOf = (level) =>
  level === "critical" || level === "high" ? vscode.DiagnosticSeverity.Error
    : level === "medium" ? vscode.DiagnosticSeverity.Warning : vscode.DiagnosticSeverity.Information;

function proposalText(d) {
  const r = d.replacement;
  if (!r) return "no proposal";
  return [r.strategy, r.package, r.version_spec].filter(Boolean).join(" ");
}

function render(capsule) {
  diagnostics.clear();
  state.byFile = new Map();
  const root = workspaceRoot();
  if (!root) return 0;
  const min = LEVELS.indexOf(cfg().minLevel);
  const perFile = new Map();
  const push = (file, line, d, message, code) => {
    const uri = vscode.Uri.joinPath(root, file);
    const key = uri.toString();
    if (!perFile.has(key)) perFile.set(key, { uri, diags: [] });
    const range = new vscode.Range(Math.max(0, line - 1), 0, Math.max(0, line - 1), 500);
    const diag = new vscode.Diagnostic(range, message, severityOf(d.risk.level));
    diag.source = "DepExit";
    diag.code = code;
    perFile.get(key).diags.push(diag);
    if (!state.byFile.has(key)) state.byFile.set(key, []);
    state.byFile.get(key).push({ line: line - 1, dep: d });
  };
  let count = 0;
  for (const d of capsule.dependencies) {
    if (LEVELS.indexOf(d.risk.level) < min) continue;
    count++;
    const codes = d.risk.indicators.map((i) => i.code).join(", ");
    const head = `${d.name} — ${d.risk.level} risk (${d.risk.score})`;
    for (const decl of d.declared) push(decl.file, decl.line, d, `${head}: ${codes}. Proposal: ${proposalText(d)}`, d.name);
    const seen = new Set();
    for (const loc of d.usage.locations) {
      const k = `${loc.file}:${loc.line}`;
      if (seen.has(k)) continue;
      seen.add(k);
      const special = loc.kind === "private_api" ? " Uses a PRIVATE API." : loc.kind === "monkeypatch" ? " MONKEYPATCHES the library." : "";
      push(loc.file, loc.line, d, `${head}.${special} Proposal: ${proposalText(d)}`, d.name);
    }
  }
  for (const { uri, diags } of perFile.values()) diagnostics.set(uri, diags);
  const s = capsule.summary;
  statusBar.text = `$(shield) DepExit: ${s.at_risk} at risk · ${s.verdict.replace(/_/g, " ")}`;
  statusBar.tooltip = s.headline;
  statusBar.show();
  return count;
}

function hoverFor(d) {
  const md = new vscode.MarkdownString(undefined, true);
  md.isTrusted = true;
  md.appendMarkdown(`**DepExit · ${d.name}** — \`${d.risk.level}\` (${d.risk.score}/100)\n\n`);
  md.appendMarkdown(`${d.risk.rationale}${d.risk.rationale_provenance === "ai" ? " _(Gemma 4)_" : ""}\n\n`);
  for (const i of d.risk.indicators.slice(0, 6)) md.appendMarkdown(`- **${i.code}**: ${i.detail}\n`);
  if (d.replacement) {
    md.appendMarkdown(`\n**Proposal** ${d.replacement.provenance === "ai" ? "_(Gemma 4)_" : ""}: \`${proposalText(d)}\` — ${d.replacement.rationale}\n`);
  }
  if (d.migration) {
    md.appendMarkdown(`\n**Migration** (${d.migration.applied ? "applied in sandbox" : "not applied"}):\n`);
    d.migration.steps.slice(0, 5).forEach((s, n) => md.appendMarkdown(`${n + 1}. ${s}\n`));
  }
  const gaps = d.compatibility_gaps || [];
  if (gaps.length) {
    md.appendMarkdown(`\n**Test gaps:**\n`);
    for (const g of gaps.slice(0, 4)) md.appendMarkdown(`- \`${g.test_id || "install"}\` ${g.baseline} → ${g.migrated} (**${g.change}**): ${g.explanation}\n`);
  } else if (d.test_results && d.test_results.status !== "not_run") {
    md.appendMarkdown(`\n**Tests:** ${d.test_results.status} on the migrated workspace.\n`);
  }
  return md;
}

async function loadAnalysis(id) {
  const capsule = await api(`/api/analyses/${id}/capsule`);
  state = { ...state, id, capsule };
  const n = render(capsule);
  output.appendLine(`Loaded capsule ${id}: ${n} at-risk dependencies shown.`);
  vscode.window.showInformationMessage(`DepExit: ${capsule.summary.headline}`, "Open Capsule", "Open Patch").then((pick) => {
    if (pick === "Open Capsule") vscode.commands.executeCommand("depexit.openCapsule");
    if (pick === "Open Patch") vscode.commands.executeCommand("depexit.openPatch");
  });
}

async function analyze() {
  const root = workspaceRoot();
  const repo = await vscode.window.showInputBox({
    prompt: "GitHub repository to analyse (DepExit clones it and runs the tests in Docker)",
    value: (root && gitRemote(root)) || "https://github.com/rishrek/LinkWatch",
  });
  if (!repo) return;
  const created = await api("/api/analyses", false, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ repo_url: repo }),
  });
  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "DepExit", cancellable: true },
    async (progress, token) => {
      let last = "";
      for (; ;) {
        if (token.isCancellationRequested) return;
        const job = await api(`/api/analyses/${created.id}`);
        const running = job.stages.filter((s) => s.status === "running").map((s) => s.label).join(" · ");
        if (running && running !== last) { progress.report({ message: running }); last = running; }
        if (["completed", "completed_with_errors", "failed"].includes(job.status)) {
          if (job.status === "failed") throw new Error(job.error || "analysis failed");
          await loadAnalysis(created.id);
          return;
        }
        await new Promise((r) => setTimeout(r, 2000));
      }
    });
}

async function openText(path, language) {
  const text = await api(`/api/analyses/${state.id}${path}`, true);
  const doc = await vscode.workspace.openTextDocument({ content: text, language });
  await vscode.window.showTextDocument(doc, { preview: true });
  return doc;
}

class QuickFix {
  provideCodeActions(document, range, context) {
    const ours = context.diagnostics.filter((d) => d.source === "DepExit");
    if (!ours.length || !state.id) return [];
    const rel = vscode.workspace.asRelativePath(document.uri, false).replace(/\\/g, "/");
    const fix = new vscode.CodeAction("DepExit: replace file with its migrated version", vscode.CodeActionKind.QuickFix);
    fix.command = { command: "depexit.applyFile", title: "Apply migration", arguments: [document.uri, rel] };
    fix.diagnostics = ours;
    const show = new vscode.CodeAction("DepExit: open Exit Capsule", vscode.CodeActionKind.QuickFix);
    show.command = { command: "depexit.openCapsule", title: "Open capsule" };
    const all = new vscode.CodeAction("DepExit: apply migration to ALL files", vscode.CodeActionKind.QuickFix);
    all.command = { command: "depexit.applyAll", title: "Apply all migrations" };
    all.diagnostics = ours;
    return [fix, all, show];
  }
}

async function applyFile(uri, rel) {
  let text;
  try {
    text = await api(`/api/analyses/${state.id}/migrated/${rel}`, true);
  } catch (e) {
    vscode.window.showWarningMessage(`DepExit: no migrated version of ${rel} (${e.message}).`);
    return;
  }
  const doc = await vscode.workspace.openTextDocument(uri);
  if (doc.getText() === text) {
    vscode.window.showInformationMessage(`DepExit: ${rel} needs no change.`);
    return;
  }
  const migrated = await vscode.workspace.openTextDocument({ content: text, language: doc.languageId });
  await vscode.commands.executeCommand("vscode.diff", uri, migrated.uri, `${rel} ↔ DepExit migrated`);
  const ok = await vscode.window.showWarningMessage(`Apply DepExit's migrated version of ${rel}?`, { modal: true }, "Apply");
  if (ok !== "Apply") return;
  const edit = new vscode.WorkspaceEdit();
  edit.replace(uri, new vscode.Range(0, 0, doc.lineCount, 0), text);
  await vscode.workspace.applyEdit(edit);
}

async function applyAll() {
  if (!state.id) throw new Error("load an analysis first (DepExit: Load Analysis by ID)");
  const root = workspaceRoot();
  if (!root) throw new Error("open the cloned repository as a workspace folder");
  const listing = await api(`/api/analyses/${state.id}/files`);
  const changed = listing.files.filter((f) => f.status === "modified" || f.status === "added");
  if (!changed.length) {
    vscode.window.showInformationMessage("DepExit: nothing to migrate.");
    return;
  }
  const picks = await vscode.window.showQuickPick(
    changed.map((f) => ({ label: f.path, description: f.status, picked: true })),
    { canPickMany: true, title: `DepExit: ${changed.length} file(s) changed by the migration. Untick any to skip.` });
  if (!picks || !picks.length) return;
  const ok = await vscode.window.showWarningMessage(
    `Apply DepExit's Docker-verified migration to ${picks.length} file(s)? Changes stay unsaved so you can undo.`,
    { modal: true }, "Apply All");
  if (ok !== "Apply All") return;

  const edit = new vscode.WorkspaceEdit();
  let applied = 0;
  for (const p of picks) {
    const uri = vscode.Uri.joinPath(root, p.label);
    const text = await api(`/api/analyses/${state.id}/migrated/${p.label}`, true);
    if (p.description === "added") {
      edit.createFile(uri, { overwrite: true, contents: Buffer.from(text, "utf8") });
    } else {
      const doc = await vscode.workspace.openTextDocument(uri);
      if (doc.getText() === text) continue;
      edit.replace(uri, new vscode.Range(0, 0, doc.lineCount, 0), text);
    }
    applied++;
  }
  await vscode.workspace.applyEdit(edit);
  vscode.window.showInformationMessage(`DepExit: applied migration to ${applied} file(s). Review, run your tests, then save.`);
}

function activate(context) {
  diagnostics = vscode.languages.createDiagnosticCollection("depexit");
  output = vscode.window.createOutputChannel("DepExit");
  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  statusBar.command = "depexit.openCapsule";
  const wrap = (fn) => async (...args) => {
    try { await fn(...args); } catch (e) { vscode.window.showErrorMessage(`DepExit: ${e.message}`); output.appendLine(String(e.stack || e)); }
  };
  context.subscriptions.push(
    diagnostics, output, statusBar,
    vscode.commands.registerCommand("depexit.analyze", wrap(analyze)),
    vscode.commands.registerCommand("depexit.load", wrap(async () => {
      let items = [];
      try { items = (await api("/api/analyses")).items.filter((i) => i.status !== "failed"); } catch { /* API down */ }
      const pick = items.length
        ? await vscode.window.showQuickPick(items.map((i) => ({ label: i.id, description: `${i.repo_url} · ${i.status}` })))
        : { label: await vscode.window.showInputBox({ prompt: "Analysis ID (dx_...)" }) };
      if (pick && pick.label) await loadAnalysis(pick.label);
    })),
    vscode.commands.registerCommand("depexit.openCapsule", wrap(async () => {
      if (!state.id) throw new Error("load an analysis first (DepExit: Load Analysis by ID)");
      const doc = await openText("/capsule.md", "markdown");
      await vscode.commands.executeCommand("markdown.showPreview", doc.uri);
    })),
    vscode.commands.registerCommand("depexit.openPatch", wrap(async () => {
      if (!state.id) throw new Error("load an analysis first");
      await openText("/patch.diff", "diff");
    })),
    vscode.commands.registerCommand("depexit.applyFile", wrap(applyFile)),
    vscode.commands.registerCommand("depexit.applyAll", wrap(applyAll)),
    vscode.commands.registerCommand("depexit.clear", () => { diagnostics.clear(); statusBar.hide(); state.id = null; }),
    vscode.languages.registerCodeActionsProvider({ scheme: "file" }, new QuickFix(), { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }),
    vscode.languages.registerHoverProvider({ scheme: "file" }, {
      provideHover(document, position) {
        const hits = (state.byFile.get(document.uri.toString()) || []).filter((h) => h.line === position.line);
        if (!hits.length) return null;
        const uniq = [...new Map(hits.map((h) => [h.dep.name, h.dep])).values()];
        return new vscode.Hover(uniq.map(hoverFor));
      },
    }),
  );
}

function deactivate() { }

module.exports = { activate, deactivate };
