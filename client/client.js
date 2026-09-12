#!/usr/bin/env node

await runDevServer();

async function startBrowserClient() {
  const { PipecatClient, RTVIEvent } = await import("@pipecat-ai/client-js");
  const { SmallWebRTCTransport } = await import(
    "@pipecat-ai/small-webrtc-transport"
  );

  document.body.innerHTML = `
    <main>
      <h1>Mio</h1>
      <p id="status">Disconnected</p>
      <div id="log"></div>
      <video id="local-cam" autoplay muted playsinline></video>
      <div class="actions">
        <button id="connect" type="button">Connect</button>
      </div>
    </main>
    <audio id="bot-audio" autoplay></audio>
  `;

  const statusEl = document.getElementById("status");
  const logEl = document.getElementById("log");
  const connectBtn = document.getElementById("connect");
  const botAudio = document.getElementById("bot-audio");
  const localCam = document.getElementById("local-cam");

  let client = null;
  let connected = false;

  function setStatus(text) {
    statusEl.textContent = text;
    console.log(text);
  }

  function addLog(text, role) {
    const line = document.createElement("p");
    line.className = role;
    line.textContent = text;
    logEl.appendChild(line);
    logEl.scrollTop = logEl.scrollHeight;
  }

  function attachBotAudio(track) {
    botAudio.srcObject = new MediaStream([track]);
    botAudio.play().catch((error) => {
      setStatus(`Speaker blocked: ${error.message}`);
    });
  }

  function attachLocalCam(track) {
    localCam.srcObject = new MediaStream([track]);
  }

  function createClient() {
    const pcClient = new PipecatClient({
      transport: new SmallWebRTCTransport({
        iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
      }),
      enableCam: true,
      enableMic: true,
      callbacks: {
        onConnected: () => setStatus("Connected"),
        onDisconnected: () => {
          connected = false;
          connectBtn.textContent = "Connect";
          botAudio.srcObject = null;
          localCam.srcObject = null;
          setStatus("Disconnected");
        },
        onBotReady: () => {
          setStatus("Ready — say Hey Mio");
          addLog("Mio is ready. Say Hey Mio to talk.", "meta");
          botAudio.play().catch(() => {});
        },
        onBotStartedSpeaking: () => {
          client?.enableMic(false);
          setStatus("Mio is speaking");
        },
        onBotStoppedSpeaking: () => {
          client?.enableMic(true);
          setStatus("Listening");
        },
        onUserTranscript: (data) => {
          if (data.final && data.text) addLog(data.text, "user");
        },
        onBotTranscript: (data) => {
          if (data.text) addLog(data.text, "bot");
        },
        onError: (error) => {
          const message = error?.message || String(error);
          setStatus(message);
          addLog(message, "meta");
        },
      },
    });

    pcClient.on(RTVIEvent.TrackStarted, (track, participant) => {
      if (!participant?.local && track.kind === "audio") {
        attachBotAudio(track);
      }
      if (participant?.local && track.kind === "audio") {
        track
          .applyConstraints({
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          })
          .catch(() => {});
      }
      if (participant?.local && track.kind === "video") {
        attachLocalCam(track);
      }
    });

    return pcClient;
  }

  async function connect() {
    connectBtn.disabled = true;
    setStatus("Connecting (allow mic and camera if asked)…");
    try {
      client = createClient();
      await client.startBotAndConnect({
        endpoint: "/start",
        requestData: {
          transport: "webrtc",
          enableDefaultIceServers: true,
        },
      });
      connected = true;
      connectBtn.textContent = "Disconnect";
      client.enableMic(true);
    } catch (error) {
      const message = error?.message || String(error);
      setStatus(message);
      addLog(message, "meta");
      client = null;
    } finally {
      connectBtn.disabled = false;
    }
  }

  async function disconnect() {
    connectBtn.disabled = true;
    try {
      await client?.disconnect();
    } finally {
      client = null;
      connectBtn.disabled = false;
    }
  }

  connectBtn.addEventListener("click", () => {
    if (connected) {
      disconnect();
    } else {
      connect();
    }
  });

  connect();
}

async function runDevServer() {
  const { createServer, request: httpRequest } = await import("node:http");
  const { request: httpsRequest } = await import("node:https");
  const { execFile } = await import("node:child_process");
  const { mkdirSync, writeFileSync } = await import("node:fs");
  const { fileURLToPath } = await import("node:url");
  const esbuild = await import("esbuild");
  const botOrigin = process.env.PIPECAT_BASE_URL || "http://localhost:8860";
  const port = Number(process.env.CLIENT_PORT) || 5173;

  let js = "";
  const ctx = await esbuild.context({
    stdin: {
      contents: `(${startBrowserClient.toString()})();`,
      resolveDir: fileURLToPath(new URL(".", import.meta.url)),
      sourcefile: "browser.js",
    },
    bundle: true,
    format: "esm",
    platform: "browser",
    write: false,
    plugins: [
      {
        name: "capture-bundle",
        setup(build) {
          build.onEnd((result) => {
            if (result.errors.length) {
              for (const error of result.errors) console.error(error.text);
              return;
            }
            if (result.outputFiles?.[0]) js = result.outputFiles[0].text;
          });
        },
      },
    ],
  });
  await ctx.watch();

  const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>Mio</title>
  </head>
  <body>
    <script type="module" src="/client.js"></script>
  </body>
</html>`;

  createServer((req, res) => {
    const url = req.url.split("?")[0];
    if (url === "/" || url === "/index.html") {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(html);
      return;
    }
    if (url === "/client.js") {
      res.writeHead(200, { "content-type": "text/javascript; charset=utf-8" });
      res.end(js);
      return;
    }
    if (
      url.startsWith("/start") ||
      url.startsWith("/sessions") ||
      url.startsWith("/api")
    ) {
      const target = new URL(req.url, botOrigin);
      const send = target.protocol === "https:" ? httpsRequest : httpRequest;
      const upstream = send(
        target,
        {
          method: req.method,
          headers: { ...req.headers, host: target.host },
        },
        (upRes) => {
          res.writeHead(upRes.statusCode, upRes.headers);
          upRes.pipe(res);
        },
      );
      upstream.on("error", (err) => {
        res.writeHead(502);
        res.end(String(err));
      });
      req.pipe(upstream);
      return;
    }
    res.writeHead(404);
    res.end();
  }).listen(port, () => {
    const origin = `http://localhost:${port}`;
    const browser = process.env.MIO_BROWSER || "firefox";
    console.log(`Mio client: ${origin} (bot ${botOrigin})`);
    // SSH/make have no DISPLAY. Point Firefox at the local labwc session
    // (:0, plus xauth and the user runtime dir for PipeWire audio).
    const env = { ...process.env };
    if (!env.DISPLAY) env.DISPLAY = ":0";
    if (!env.XAUTHORITY && env.HOME) env.XAUTHORITY = `${env.HOME}/.Xauthority`;
    if (!env.XDG_RUNTIME_DIR) env.XDG_RUNTIME_DIR = `/run/user/${process.getuid()}`;
    const args = [origin];
    if (/firefox/i.test(browser)) {
      const profileDir = fileURLToPath(new URL("./.firefox-profile", import.meta.url));
      mkdirSync(profileDir, { recursive: true });
      // Dedicated profile: no session restore, auto-allow mic/cam/autoplay.
      writeFileSync(
        `${profileDir}/user.js`,
        [
          'user_pref("media.navigator.permission.disabled", true);',
          'user_pref("permissions.default.microphone", 1);',
          'user_pref("permissions.default.camera", 1);',
          'user_pref("media.autoplay.default", 0);',
          'user_pref("browser.sessionstore.resume_from_crash", false);',
          'user_pref("browser.startup.page", 0);',
        ].join("\n"),
      );
      args.unshift("--new-instance", "--profile", profileDir);
    }
    execFile(browser, args, { env }, (error) => {
      if (error) {
        console.warn(`Could not open ${browser}: ${error.message}`);
        console.warn(`Open ${origin} in Firefox to connect the speaker and mic.`);
      }
    });
  });
}
