const state = {
  catalog: null,
  workflowId: null,
};

const $ = (id) => document.getElementById(id);

function sharedValues() {
  return {
    port: $("port").value.trim(),
    baudrate: $("baudrate").value.trim(),
    zeros: $("zeros").value.trim(),
    zeros_positional: $("zeros").value.trim(),
  };
}

function formValues(root) {
  const values = { ...sharedValues() };
  root.querySelectorAll("[data-field]").forEach((el) => {
    const key = el.dataset.field;
    if (el.type === "checkbox") {
      values[key] = el.checked;
    } else {
      values[key] = el.value;
    }
  });
  return values;
}

function fieldControl(flag) {
  const wrap = document.createElement("label");
  wrap.textContent = flag.help ? `${flag.key} — ${flag.help}` : flag.key;
  let input;
  if (flag.kind === "bool") {
    input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(flag.default);
  } else if (flag.kind === "choice" && flag.choices) {
    input = document.createElement("select");
    flag.choices.forEach((choice) => {
      const option = document.createElement("option");
      option.value = choice;
      option.textContent = choice;
      if (choice === flag.default) option.selected = true;
      input.append(option);
    });
  } else {
    input = document.createElement("input");
    input.type = "text";
    if (flag.default !== null && flag.default !== undefined) {
      input.value = String(flag.default);
    }
    if (flag.required) input.required = true;
  }
  input.dataset.field = flag.key;
  wrap.append(input);
  return wrap;
}

function toolById(id) {
  return state.catalog.tools.find((tool) => tool.id === id);
}

async function refreshCommand(stepEl, workflowId, stepId) {
  const pre = stepEl.querySelector(".command");
  const payload = {
    workflow_id: workflowId,
    step_id: stepId,
    values: formValues(document),
  };
  const response = await fetch("/api/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    pre.textContent = data.error || "Could not build command";
    pre.classList.add("err");
    return data;
  }
  pre.classList.remove("err");
  pre.textContent = data.command;
  return data;
}

function renderWorkflow(workflow) {
  const stage = $("stage");
  stage.replaceChildren();

  const banner = document.createElement("div");
  banner.className = "banner";
  banner.innerHTML = `<h2>${workflow.title}</h2>
    <p>${workflow.summary}</p>
    <p>${workflow.when}</p>
    <p class="caution">${workflow.caution}</p>`;
  stage.append(banner);

  const params = document.createElement("div");
  params.className = "params";
  params.id = "workflow-params";
  workflow.params.forEach((flag) => params.append(fieldControl(flag)));
  stage.append(params);

  workflow.steps.forEach((step, index) => {
    const tool = toolById(step.tool);
    const card = document.createElement("article");
    card.className = "step";
    card.dataset.stepId = step.id;
    card.innerHTML = `
      <h3>${index + 1}. ${step.title}</h3>
      <p>${step.body}</p>
      <div class="meta">
        <span class="tag">${tool.module}</span>
        ${tool.needs_tty ? '<span class="tag tty">needs TTY</span>' : '<span class="tag">runnable here</span>'}
        ${tool.moves_hardware ? '<span class="tag move">moves hardware</span>' : ""}
      </div>
      <pre class="command">building…</pre>
      <div class="actions"></div>
      <pre class="log" hidden></pre>
    `;
    const actions = card.querySelector(".actions");
    const copy = document.createElement("button");
    copy.className = "act secondary";
    copy.textContent = "Copy command";
    copy.addEventListener("click", async () => {
      const data = await refreshCommand(card, workflow.id, step.id);
      if (data.command) await navigator.clipboard.writeText(data.command);
    });
    const run = document.createElement("button");
    run.className = "act";
    run.textContent = tool.needs_tty ? "TTY — copy instead" : "Run this step";
    run.disabled = tool.needs_tty;
    run.addEventListener("click", () => runStep(card, workflow, step, tool));
    actions.append(copy, run);
    stage.append(card);
    refreshCommand(card, workflow.id, step.id);
  });

  document.querySelectorAll("[data-field], #shared-form input").forEach((el) => {
    el.addEventListener("input", () => {
      workflow.steps.forEach((step) => {
        const card = stage.querySelector(`[data-step-id="${step.id}"]`);
        if (card) refreshCommand(card, workflow.id, step.id);
      });
    });
    el.addEventListener("change", () => {
      workflow.steps.forEach((step) => {
        const card = stage.querySelector(`[data-step-id="${step.id}"]`);
        if (card) refreshCommand(card, workflow.id, step.id);
      });
    });
  });
}

async function runStep(card, workflow, step, tool) {
  const log = card.querySelector(".log");
  log.hidden = false;
  log.textContent = "Running…";
  log.classList.remove("ok", "err");
  const response = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      workflow_id: workflow.id,
      step_id: step.id,
      confirm: true,
      values: formValues(document),
    }),
  });
  const data = await response.json();
  if (data.skipped) {
    log.classList.add("err");
    log.textContent = data.skip_reason + "\n\n" + (data.command || "");
    return;
  }
  const chunks = [
    `$ ${data.command || ""}`,
    data.stdout || "",
    data.stderr || "",
    `exit ${data.returncode}`,
  ].filter(Boolean);
  log.textContent = chunks.join("\n");
  log.classList.add(data.returncode === 0 ? "ok" : "err");
}

function renderRail() {
  const rail = $("rail");
  rail.replaceChildren();
  state.catalog.workflows.forEach((workflow) => {
    const button = document.createElement("button");
    button.type = "button";
    button.innerHTML = `${workflow.title}<span>${workflow.summary}</span>`;
    button.addEventListener("click", () => {
      state.workflowId = workflow.id;
      rail.querySelectorAll("button").forEach((node) => node.classList.toggle("active", node === button));
      renderWorkflow(workflow);
    });
    rail.append(button);
  });
}

async function boot() {
  const catalog = await (await fetch("/api/catalog")).json();
  state.catalog = catalog;
  $("port").value = catalog.shared.port;
  $("baudrate").value = catalog.shared.baudrate;
  $("zeros").value = catalog.shared.zeros;
  renderRail();
  const first = catalog.workflows[0];
  if (first) {
    state.workflowId = first.id;
    $("rail").querySelector("button")?.classList.add("active");
    renderWorkflow(first);
  }
}

boot();
