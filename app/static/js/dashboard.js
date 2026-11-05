(() => {
  const HISTORY_LIMIT = 60;
  const GAUGE_LEN = 220;

  const els = {
    wsDot: document.getElementById("ws-dot"),
    wsLabel: document.getElementById("ws-label"),
    dataSource: document.getElementById("data-source"),
    updatedAt: document.getElementById("updated-at"),
    tempValue: document.getElementById("temp-value"),
    tempTag: document.getElementById("temp-tag"),
    tempNote: document.getElementById("temp-note"),
    tempSecondary: document.getElementById("temp-secondary"),
    tempArc: document.getElementById("temp-arc"),
    turbValue: document.getElementById("turb-value"),
    turbTag: document.getElementById("turb-tag"),
    turbNote: document.getElementById("turb-note"),
    turbRaw: document.getElementById("turb-raw"),
    turbArc: document.getElementById("turb-arc"),
    levelValue: document.getElementById("level-value"),
    levelTag: document.getElementById("level-tag"),
    levelNote: document.getElementById("level-note"),
    tankFill: document.getElementById("tank-fill"),
    levelCm: document.getElementById("level-cm"),
    levelDistance: document.getElementById("level-distance"),
    levelTank: document.getElementById("level-tank"),
    statusMessage: document.getElementById("status-message"),
    qualityMessage: document.getElementById("quality-message"),
  };

  const history = {
    labels: [],
    temperature: [],
    turbidity: [],
    level: [],
  };

  let chart = null;
  let ws = null;
  let retryTimer = null;

  function setConnection(state) {
    els.wsDot.className = `status-dot ${state}`;
    els.wsLabel.textContent =
      state === "live" ? "Live" : state === "connecting" ? "Connecting" : "Offline";
  }

  function setTag(el, text, kind) {
    el.textContent = text;
    el.className = `tag ${kind || ""}`.trim();
  }

  function setGauge(arc, value, max, extraClass) {
    const has = value != null && !Number.isNaN(Number(value));
    const pct = has ? Math.max(0, Math.min(1, Number(value) / max)) : 0;
    arc.style.strokeDashoffset = String(GAUGE_LEN - GAUGE_LEN * pct);
    if (extraClass !== undefined) {
      arc.className.baseVal = extraClass
        ? `gauge-fill turb ${extraClass}`
        : "gauge-fill turb";
    }
  }

  function fmt(n, digits = 1) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    return Number(n).toFixed(digits);
  }

  function ensureChart() {
    if (chart || typeof Chart === "undefined") return;
    const ctx = document.getElementById("trend-chart");
    chart = new Chart(ctx, {
      type: "line",
      data: {
        labels: history.labels,
        datasets: [
          {
            label: "Temp °C",
            data: history.temperature,
            borderColor: "#2f6fed",
            backgroundColor: "transparent",
            borderWidth: 2,
            tension: 0.25,
            pointRadius: 0,
          },
          {
            label: "Turbidity",
            data: history.turbidity,
            borderColor: "#9a6700",
            backgroundColor: "transparent",
            borderWidth: 2,
            tension: 0.25,
            pointRadius: 0,
          },
          {
            label: "Level %",
            data: history.level,
            borderColor: "#0b6e6a",
            backgroundColor: "transparent",
            borderWidth: 2,
            tension: 0.25,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            labels: {
              color: "#5c6b7a",
              boxWidth: 10,
              font: { family: "Source Sans 3", size: 12 },
            },
          },
          tooltip: {
            backgroundColor: "#ffffff",
            titleColor: "#1a2332",
            bodyColor: "#5c6b7a",
            borderColor: "#d8dee6",
            borderWidth: 1,
          },
        },
        scales: {
          x: {
            ticks: { color: "#8a97a5", maxTicksLimit: 8, font: { size: 11 } },
            grid: { color: "#eef2f6" },
            border: { color: "#d8dee6" },
          },
          y: {
            ticks: { color: "#8a97a5", font: { size: 11 } },
            grid: { color: "#eef2f6" },
            border: { color: "#d8dee6" },
          },
        },
      },
    });
  }

  function pushHistory(reading) {
    const t = new Date(reading.timestamp);
    const label = t.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    history.labels.push(label);
    history.temperature.push(reading.temperature?.celsius ?? null);
    history.turbidity.push(reading.turbidity?.index ?? null);
    history.level.push(reading.waterLevel?.percentage ?? null);

    if (history.labels.length > HISTORY_LIMIT) {
      history.labels.shift();
      history.temperature.shift();
      history.turbidity.shift();
      history.level.shift();
    }

    ensureChart();
    if (chart) {
      chart.data.labels = history.labels;
      chart.data.datasets[0].data = history.temperature;
      chart.data.datasets[1].data = history.turbidity;
      chart.data.datasets[2].data = history.level;
      chart.update("none");
    }
  }

  function renderReading(reading) {
    const temp = reading.temperature || {};
    const turb = reading.turbidity || {};
    const level = reading.waterLevel || {};

    els.dataSource.textContent = reading.source || "—";
    els.updatedAt.textContent = new Date(reading.timestamp).toLocaleTimeString();

    els.tempValue.textContent = fmt(temp.celsius);
    setTag(
      els.tempTag,
      temp.connected ? "Connected" : "No sensor",
      temp.connected ? "ok" : "bad"
    );
    els.tempNote.textContent = temp.connected
      ? "DS18B20 probe"
      : "DS18B20 not detected — check DATA on A1 + 4.7k pull-up to 5V";
    els.tempSecondary.textContent =
      temp.fahrenheit != null ? `${fmt(temp.fahrenheit)} °F` : "— °F";
    setGauge(els.tempArc, temp.celsius, 50);

    const turbIndex = turb.index;
    // Prefer index; if missing but raw exists, still show raw so the panel is never blank
    if (turbIndex != null) {
      els.turbValue.textContent = fmt(turbIndex, 0);
    } else if (turb.raw != null) {
      els.turbValue.textContent = fmt(turb.raw, 0);
    } else {
      els.turbValue.textContent = "—";
    }
    if (turb.status) {
      setTag(els.turbTag, turb.status, String(turb.status).toLowerCase());
    } else if (turb.raw != null) {
      setTag(els.turbTag, "Live", "ok");
    } else {
      setTag(els.turbTag, "—", "");
    }
    if (turbIndex != null || turb.raw != null) {
      els.turbNote.textContent = "Dirtiness 0–100 · CLEAR < 20 · CLOUDY < 50";
    } else {
      els.turbNote.textContent = "Waiting for turbidity reading";
    }
    const rawPart = turb.raw != null ? `ADC ${turb.raw}` : "ADC —";
    const voltPart =
      turb.voltage != null ? ` · ${fmt(turb.voltage, 2)} V` : "";
    els.turbRaw.textContent = `${rawPart}${voltPart}`;
    let turbClass = "";
    if (turbIndex != null) {
      turbClass = turbIndex < 20 ? "" : turbIndex < 50 ? "warn" : "bad";
    }
    setGauge(els.turbArc, turbIndex, 100, turbClass);

    const pct = level.percentage;
    els.levelValue.textContent = pct != null ? fmt(pct, 0) : "—";
    if (level.valid === true) {
      setTag(els.levelTag, "In range", "ok");
    } else if (level.valid === false) {
      setTag(els.levelTag, "Out of range", "bad");
    } else {
      setTag(els.levelTag, "—", "");
    }
    els.levelNote.textContent =
      level.distanceCm != null
        ? `Echo ${fmt(level.distanceCm)} cm · HC-SR04`
        : "Waiting for ultrasonic reading";
    els.tankFill.style.height =
      pct != null ? `${Math.max(0, Math.min(100, pct))}%` : "0%";
    els.levelCm.textContent =
      level.levelCm != null ? `${fmt(level.levelCm)} cm` : "—";
    els.levelDistance.textContent =
      level.distanceCm != null ? `${fmt(level.distanceCm)} cm` : "—";
    els.levelTank.textContent =
      level.tankHeightCm != null ? `${level.tankHeightCm} cm` : "—";

    if (turb.status === "CLEAR") {
      els.qualityMessage.textContent =
        "Water looks clear based on the turbidity index.";
    } else if (turb.status === "CLOUDY") {
      els.qualityMessage.textContent =
        "Water is moderately cloudy — consider filtration.";
    } else if (turb.status === "DIRTY") {
      els.qualityMessage.textContent =
        "High turbidity detected — water may need attention.";
    } else {
      els.qualityMessage.textContent = "Waiting for live turbidity status.";
    }

    pushHistory(reading);
  }

  function renderStatus(status) {
    if (!status) return;
    if (status.mode) els.dataSource.textContent = status.mode;
    els.statusMessage.textContent =
      status.message || "Awaiting publisher status.";
  }

  function wsUrl() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/ws`;
  }

  function connect() {
    setConnection("connecting");
    ws = new WebSocket(wsUrl());

    ws.onopen = () => {
      setConnection("live");
      ws.send(
        JSON.stringify({
          action: "subscribe",
          topics: ["sensors/water/data", "sensors/water/status"],
        })
      );
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      if (msg.type !== "message") return;
      if (msg.topic === "sensors/water/data") renderReading(msg.payload);
      if (msg.topic === "sensors/water/status") renderStatus(msg.payload);
    };

    ws.onclose = () => {
      setConnection("offline");
      clearTimeout(retryTimer);
      retryTimer = setTimeout(connect, 2000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: "ping" }));
    }
  }, 15000);

  // Empty gauges until the first live Arduino reading arrives
  setGauge(els.tempArc, null, 50);
  setGauge(els.turbArc, null, 100, "");
  connect();
})();
