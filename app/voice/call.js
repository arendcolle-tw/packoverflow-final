// Call tab: a live voice call with the PackOverflow agent (ElevenLabs web SDK), or the recorded call as a fallback.
// While the call runs, the two names appear when the agent's who_knows tool answers.
(function () {
  const $ = (id) => document.getElementById(id);
  const state = $("callstate");
  const callBtn = $("callbtn");
  const playBtn = $("playbtn");
  const audio = $("recorded");
  let convo = null;

  const set = (text) => { state.textContent = text; };
  const caption = (who, text) => {
    const line = document.createElement("p");
    line.className = "line " + who;
    line.textContent = text;
    const box = $("captions");
    box.appendChild(line);
    while (box.children.length > 4) box.removeChild(box.firstChild);
  };

  function reset() {
    $("callnames").classList.remove("on");
    $("captions").innerHTML = "";
    $("busyname").textContent = "...";
    $("knowname").textContent = "...";
    $("knowwhy").textContent = "";
    $("knowwhen").textContent = "";
    $("datatag").hidden = true;
  }

  // The who_knows tool result, as our own endpoint returned it.
  function showNames(r) {
    if (!r || !r.who_knows) return;
    $("busyname").textContent = (r.busiest_on_this && r.busiest_on_this.name) || r.who_knows.name;
    $("knowname").textContent = r.who_knows.name;
    const words = (r.who_knows.their_own_words || [])[0] || "";
    $("knowwhy").textContent = words.replace(/^[a-z ]+: /, "");
    $("knowwhen").textContent = "Last reasoned about it " + r.who_knows.last_reasoned;
    $("datatag").textContent = r.data || "";
    $("datatag").hidden = !r.data;
    $("callnames").classList.add("on");
  }

  function parseResult(payload) {
    let raw = payload && (payload.full_tool_result || payload.tool_result || payload.result);
    for (let i = 0; i < 3 && typeof raw === "string"; i++) {
      try { raw = JSON.parse(raw); } catch { return null; }
    }
    if (raw && raw.who_knows) return raw;
    if (raw && typeof raw === "object") for (const v of Object.values(raw)) if (v && v.who_knows) return v;
    return null;
  }

  async function startCall() {
    if (!window.ElevenLabsClient) { set("The call library did not load. Play the recorded call instead."); return; }
    audio.pause();
    reset();
    callBtn.disabled = true;
    set("Asking for your microphone...");
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      set("No microphone access. Allow the mic, or play the recorded call.");
      callBtn.disabled = false;
      return;
    }
    set("Dialing...");
    let session;
    try {
      const res = await fetch("/api/voice/session", { method: "POST" });
      session = await res.json();
      if (!res.ok) throw new Error(session.error || "Could not start a call.");
    } catch (err) {
      set(err.message + " ");
      callBtn.disabled = false;
      return;
    }
    try {
      convo = await window.ElevenLabsClient.Conversation.startSession({
        signedUrl: session.signedUrl,
        connectionType: "websocket",
        onConnect: () => { set("Connected. Ask what you need to know."); callBtn.textContent = "Hang up"; callBtn.disabled = false; callBtn.classList.add("live"); },
        onDisconnect: () => { set("Call ended."); callBtn.textContent = "Call"; callBtn.disabled = false; callBtn.classList.remove("live"); convo = null; },
        onError: (msg) => set("Call problem: " + msg),
        onModeChange: ({ mode }) => { if (convo) set(mode === "speaking" ? "PackOverflow is speaking..." : "Listening..."); },
        onMessage: ({ source, message }) => caption(source === "user" ? "you" : "agent", message),
        onAgentToolResponse: (p) => showNames(parseResult(p)),
      });
    } catch (err) {
      set("Could not connect the call (" + (err && err.message ? err.message : "network") + "). Play the recorded call instead.");
      callBtn.disabled = false;
    }
  }

  callBtn.addEventListener("click", () => (convo ? convo.endSession() : startCall()));

  // Recorded call: names appear at the moment the agent got its answer in the original call.
  let timeline = null;
  fetch("/voice/recorded-call.json").then((r) => (r.ok ? r.json() : null)).then((t) => {
    timeline = t;
    if (!t) { playBtn.disabled = true; playBtn.textContent = "Recorded call coming soon"; }
  }).catch(() => {});
  playBtn.addEventListener("click", () => {
    if (convo) convo.endSession();
    if (!audio.paused) { audio.pause(); return; }
    reset();
    audio.currentTime = 0;
    audio.play();
  });
  audio.addEventListener("play", () => { playBtn.textContent = "Pause recorded call"; set("Playing a recorded call with this same agent."); });
  audio.addEventListener("pause", () => { playBtn.textContent = "Play recorded call"; });
  audio.addEventListener("timeupdate", () => {
    if (!timeline) return;
    if (audio.currentTime >= timeline.names_at && !$("callnames").classList.contains("on")) showNames(timeline.result);
    for (const c of timeline.captions || []) {
      if (!c.shown && audio.currentTime >= c.at) { c.shown = true; caption(c.who, c.text); }
    }
  });
  audio.addEventListener("ended", () => { (timeline && timeline.captions || []).forEach((c) => (c.shown = false)); set("Recorded call ended."); });
  audio.addEventListener("seeked", () => { if (audio.currentTime < 1) (timeline && timeline.captions || []).forEach((c) => (c.shown = false)); });
})();
