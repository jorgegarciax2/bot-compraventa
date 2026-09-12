"use strict";
/* Panel de tbot: formulario -> tareas en el servidor -> gráficos y tablas. */

const $ = (s) => document.querySelector(s);

// Si la sesión caduca, el servidor responde 401 a todo: no tiene sentido seguir
// pintando una página muerta, así que se vuelve a la entrada.
async function pedir(url, opciones) {
  const r = await fetch(url, opciones);
  if (r.status === 401) { location.href = "/entrar"; throw new Error("sesión caducada"); }
  return r;
}
const crear = (t, cls, txt) => {
  const e = document.createElement(t);
  if (cls) e.className = cls;
  if (txt !== undefined) e.textContent = txt;
  return e;
};

const COLORES = ["#4c9aff", "#f2a33c", "#2fbf87", "#e5606b", "#a78bfa", "#38bdf8"];
const NUM = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const NUM0 = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 0 });
const pct = (v, d = 2) => (v === null || v === undefined) ? "—" : (v * 100).toFixed(d) + " %";
const dec = (v, d = 2) => (v === null || v === undefined) ? "—" : Number(v).toFixed(d);
const fecha = (ms) => new Date(ms).toISOString().slice(0, 10);
// El mismo gráfico sirve para ocho años de backtest y para diez minutos en vivo:
// la etiqueta se ajusta al recorrido real del eje.
function etiquetaX(ms, recorrido) {
  const d = new Date(ms);
  if (recorrido < 6 * 3600e3) return d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  if (recorrido < 3 * 86400e3) return d.toLocaleString("es-ES", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  return fecha(ms);
}

const estado = {
  arranque: null,
  mercado: null,
  resultados: [],      // último backtest/comparación
  sondeo: null,
  lineasVistas: 0,
};

/* ------------------------------------------------------------------ arranque */
async function arrancar() {
  let d;
  try {
    d = await (await pedir("/api/arranque")).json();
  } catch (e) {
    return consola("No hay conexión con el servidor: " + e.message, "error");
  }
  if (d.error) return consola(d.error, "error");
  estado.arranque = d;

  $("#chip-python").textContent = "python " + d.python;
  if (d.autenticado) {
    const salir = crear("a", "chip chip-salir", "salir");
    salir.href = "/salir";
    salir.title = "Cerrar la sesión en este navegador";
    document.querySelector(".avisos").appendChild(salir);
  }

  // mercados
  const cont = $("#mercados");
  cont.innerHTML = "";
  Object.keys(d.universo).forEach((m) => {
    const b = crear("button", null, { crypto: "cripto", equity: "acciones", synthetic: "sintético" }[m] || m);
    b.dataset.mercado = m;
    b.onclick = () => elegirMercado(m);
    cont.appendChild(b);
  });

  // estrategias
  const sel = $("#estrategia");
  sel.innerHTML = "";
  d.estrategias.forEach((e) => sel.appendChild(new Option(e.id.replace(/_/g, " "), e.id)));
  sel.onchange = pintarEstrategia;

  $("#capital").value = d.backtest.capital_inicial;
  elegirMercado(d.universo.crypto ? "crypto" : Object.keys(d.universo)[0]);
  pintarEstrategia();
  cablearBotones();
}

function elegirMercado(m) {
  estado.mercado = m;
  document.querySelectorAll("#mercados button").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.mercado === m)));

  const u = estado.arranque.universo[m];
  const cont = $("#simbolos");
  cont.innerHTML = "";
  u.simbolos.forEach((s) => {
    const l = crear("label");
    const i = crear("input");
    i.type = "checkbox"; i.value = s; i.checked = true;
    i.onchange = contarSimbolos;
    l.append(i, crear("span", null, s));
    cont.appendChild(l);
  });
  contarSimbolos();

  const c = u.costes || {};
  let nota = `Velas ${u.timeframe} desde ${u.desde}. Costes: ${dec(c.comision_bps, 1)} bps de comisión, ` +
             `${dec(c.slippage_bps, 1)} de slippage, ${dec(c.spread_bps, 1)} de spread.`;
  if (m === "equity" && !estado.arranque.alpaca) {
    nota += " ⚠︎ Sin credenciales de Alpaca en el entorno: la descarga fallará. " +
            "Exporta APCA_API_KEY_ID y APCA_API_SECRET_KEY antes de lanzar el panel.";
  }
  if (m === "synthetic") nota += " Datos generados: no hay red y sirven para probar el motor.";
  $("#nota-mercado").textContent = nota;
}

function contarSimbolos() {
  const n = simbolosElegidos().length;
  $("#cuenta-simbolos").textContent = `(${n})`;
}
const simbolosElegidos = () =>
  [...document.querySelectorAll("#simbolos input:checked")].map((i) => i.value);

function pintarEstrategia() {
  const id = $("#estrategia").value;
  const e = estado.arranque.estrategias.find((x) => x.id === id);
  $("#desc-estrategia").textContent = e ? e.descripcion : "";
  $("#params-medias").classList.toggle("oculto", id !== "cruce_medias");
}

/* -------------------------------------------------------------------- consola */
function consola(texto, nivel) {
  const c = $("#consola");
  if (!c) return;
  const l = crear("div", nivel ? "l-" + nivel : null, texto);
  c.appendChild(l);
  c.scrollTop = c.scrollHeight;
}
function limpiarConsola() { $("#consola").textContent = ""; }

function marcarEstado(txt, clase) {
  const e = $("#estado-tarea");
  e.textContent = txt;
  e.className = "estado " + (clase || "");
}

/* --------------------------------------------------------------------- tareas */
function parametros() {
  return {
    market: estado.mercado,
    symbols: simbolosElegidos(),
    timeframe: estado.arranque.universo[estado.mercado].timeframe,
    estrategia: $("#estrategia").value,
    rapida: Number($("#rapida").value) || 20,
    lenta: Number($("#lenta").value) || 50,
    capital: Number($("#capital").value) || undefined,
    desde: $("#desde").value || null,
    hasta: $("#hasta").value || null,
    sin_costes: $("#sin-costes").checked,
    rebalanceo_exacto: $("#rebalanceo-exacto").checked,
  };
}

function bloquear(si) {
  document.querySelectorAll(".acciones .btn").forEach((b) => (b.disabled = si));
}

async function lanzar(accion, extra) {
  if (estado.sondeo) return;
  const p = Object.assign(parametros(), extra || {});
  if (["backtest", "comparar", "validate", "ingest"].includes(accion) && !p.symbols.length) {
    return consola("Elige al menos un símbolo.", "error");
  }
  limpiarConsola();
  bloquear(true);
  marcarEstado("en curso…", "trabajando");
  estado.lineasVistas = 0;

  let r;
  try {
    r = await (await pedir("/api/tareas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ accion }, p)),
    })).json();
  } catch (e) {
    bloquear(false); marcarEstado("error", "error");
    return consola("No se ha podido lanzar la tarea: " + e.message, "error");
  }
  if (r.error) {
    bloquear(false); marcarEstado("error", "error");
    return consola(r.error, "error");
  }
  sondear(r.id);
}

function sondear(id) {
  estado.sondeo = setInterval(async () => {
    let s;
    try {
      s = await (await pedir(`/api/tareas/${id}?desde=${estado.lineasVistas}`)).json();
    } catch (e) { return; }
    (s.lineas || []).forEach((l) => consola(l.texto, l.nivel === "info" ? null : l.nivel));
    estado.lineasVistas = s.total_lineas;

    if (s.estado === "en_curso") { marcarEstado(`en curso · ${s.segundos}s`, "trabajando"); return; }

    clearInterval(estado.sondeo);
    estado.sondeo = null;
    bloquear(false);
    if (s.estado === "error") {
      marcarEstado("error", "error");
      consola(s.error, "error");
      return;
    }
    marcarEstado(`hecho en ${s.segundos}s`, "hecho");
    pintarResultado(s.resultado);
  }, 400);
}

/* ---------------------------------------------------------------- resultados */
function pintarResultado(r) {
  if (!r) return;
  if (r.tipo === "backtest" || r.tipo === "comparar") {
    estado.resultados = r.resultados;
    pintarGraficos();
    pintarMetricas();
    pintarOperaciones();
    $("#caja-datos").classList.add("oculto");
  } else if (r.tipo === "info") {
    tablaDatos("Inventario del almacén",
      ["market", "timeframe", "symbol", "velas", "desde", "hasta", "MB"],
      r.filas.map((f) => [f.market, f.timeframe, f.symbol, NUM0.format(f.velas),
                          String(f.desde).slice(0, 10), String(f.hasta).slice(0, 10), f.MB]));
  } else if (r.tipo === "ingest") {
    tablaDatos(`Descarga · ${r.market} ${r.timeframe}`,
      ["símbolo", "velas nuevas", "estado"],
      r.filas.map((f) => [f.symbol, NUM0.format(f.nuevas),
                          { html: etiqueta(String(f.estado) === "ok" ? "ok" : "falla", String(f.estado)) }]));
  } else if (r.tipo === "validate") {
    const filas = [];
    r.informes.forEach((i) => {
      filas.push([i.symbol, NUM0.format(i.velas), String(i.desde).slice(0, 10),
                  String(i.hasta).slice(0, 10),
                  { html: etiqueta(i.ok ? "ok" : "falla", i.ok ? "OK" : "FALLA") },
                  i.issues.length ? i.issues.map((x) => `${x.code}${x.count ? " ×" + x.count : ""}`).join(", ") : "—"]);
    });
    tablaDatos(`Calidad · ${r.validos}/${r.total} símbolos válidos`,
      ["símbolo", "velas", "desde", "hasta", "estado", "incidencias"], filas);
  }
}

const etiqueta = (clase, txt) => `<span class="etiq ${clase}">${txt}</span>`;

function tablaDatos(titulo, cabeceras, filas) {
  $("#titulo-datos").textContent = titulo;
  const t = $("#tabla-datos");
  t.innerHTML = "";
  const thead = crear("thead"), trh = crear("tr");
  cabeceras.forEach((h, i) => { const th = crear("th", i ? "num" : null, h); trh.appendChild(th); });
  thead.appendChild(trh); t.appendChild(thead);
  const tb = crear("tbody");
  filas.forEach((f) => {
    const tr = crear("tr");
    f.forEach((c, i) => {
      const td = crear("td", i ? "num" : null);
      if (c && c.html) td.innerHTML = c.html; else td.textContent = c;
      tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
  t.appendChild(tb);
  $("#caja-datos").classList.remove("oculto");
}

/* ---------------------------------------------------------------- métricas */
const FILAS_METRICAS = [
  ["Capital final", (r) => NUM.format(r.equity_final), true],
  ["Retorno total", (r) => pct(r.metricas.retorno_total)],
  ["CAGR", (r) => pct(r.metricas.cagr)],
  ["Volatilidad anual", (r) => pct(r.metricas.volatilidad)],
  ["Sharpe", (r) => dec(r.metricas.sharpe)],
  ["Sortino", (r) => dec(r.metricas.sortino)],
  ["Máx. drawdown", (r) => pct(r.metricas.max_drawdown)],
  ["Calmar", (r) => dec(r.metricas.calmar)],
  ["Mejor barra", (r) => pct(r.metricas.mejor_barra)],
  ["Peor barra", (r) => pct(r.metricas.peor_barra)],
  ["Operaciones", (r) => NUM0.format(r.n_operaciones)],
  ["Comisiones pagadas", (r) => r.metricas.comisiones_pagadas == null ? "—" : NUM.format(r.metricas.comisiones_pagadas)],
  ["Win rate", (r) => r.metricas.win_rate == null ? "—" : pct(r.metricas.win_rate)],
  ["Profit factor", (r) => r.metricas.profit_factor == null ? "∞ / —" : dec(r.metricas.profit_factor)],
  ["Barras", (r) => NUM0.format(r.metricas.barras)],
];

function pintarMetricas() {
  const R = estado.resultados;
  const t = $("#tabla-metricas");
  t.innerHTML = "";
  const thead = crear("thead"), trh = crear("tr");
  trh.appendChild(crear("th", null, "métrica"));
  R.forEach((r, i) => {
    const th = crear("th", "num");
    th.innerHTML = `<span class="punto" style="background:${COLORES[i % COLORES.length]}"></span>${r.etiqueta}`;
    trh.appendChild(th);
  });
  thead.appendChild(trh); t.appendChild(thead);

  const tb = crear("tbody");
  FILAS_METRICAS.forEach(([nombre, fn]) => {
    const tr = crear("tr");
    tr.appendChild(crear("td", null, nombre));
    R.forEach((r) => {
      const td = crear("td", "num", fn(r));
      if (nombre === "Capital final") {
        td.className += r.equity_final >= r.capital_inicial ? " pos" : " neg";
      }
      if (nombre === "Máx. drawdown" || nombre === "Peor barra") td.className += " neg";
      tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
  t.appendChild(tb);
  $("#caja-metricas").classList.remove("oculto");
}

/* -------------------------------------------------------------- operaciones */
function pintarOperaciones() {
  const sel = $("#ops-estrategia");
  sel.innerHTML = "";
  estado.resultados.forEach((r, i) => sel.appendChild(new Option(r.etiqueta, i)));
  sel.onchange = () => tablaOperaciones(Number(sel.value));
  tablaOperaciones(0);
}

function tablaOperaciones(idx) {
  const r = estado.resultados[idx];
  if (!r) return;
  const t = $("#tabla-ops");
  t.innerHTML = "";
  $("#cuenta-ops").textContent = r.n_operaciones > r.operaciones.length
    ? `(últimas ${r.operaciones.length} de ${NUM0.format(r.n_operaciones)})`
    : `(${r.operaciones.length})`;

  const cab = ["fecha", "símbolo", "lado", "unidades", "precio", "importe", "comisión", "PnL"];
  const thead = crear("thead"), trh = crear("tr");
  cab.forEach((h, i) => trh.appendChild(crear("th", i > 2 ? "num" : null, h)));
  thead.appendChild(trh); t.appendChild(thead);

  const tb = crear("tbody");
  r.operaciones.slice().reverse().forEach((o) => {
    const tr = crear("tr");
    const celdas = [
      [o.ts.slice(0, 10), ""], [o.symbol, ""],
      [o.lado, o.lado === "compra" ? "pos" : "neg"],
      [NUM.format(o.unidades).replace(/,00$/, ""), "num"],
      [NUM.format(o.precio), "num"], [NUM.format(o.notional), "num"],
      [NUM.format(o.comision), "num apagado"],
      [o.pnl === null ? "—" : NUM.format(o.pnl), "num " + (o.pnl === null ? "apagado" : o.pnl >= 0 ? "pos" : "neg")],
    ];
    celdas.forEach(([v, c]) => tr.appendChild(crear("td", c, v)));
    tb.appendChild(tr);
  });
  t.appendChild(tb);
  $("#caja-ops").classList.remove("oculto");
}

/* ---------------------------------------------------------------- gráficos */
function pintarGraficos() {
  $("#caja-grafico").classList.remove("oculto");
  const leyenda = $("#leyenda");
  leyenda.innerHTML = "";
  estado.resultados.forEach((r, i) => {
    const s = crear("span");
    const c = crear("i"); c.style.background = COLORES[i % COLORES.length];
    s.append(c, crear("span", null, r.etiqueta));
    leyenda.appendChild(s);
  });
  redibujar();
}

function redibujar() {
  const R = estado.resultados;
  if (!R.length) return;
  const log = $("#escala-log").checked;
  const base100 = $("#normalizar").checked;

  const series = R.map((r, i) => ({
    nombre: r.etiqueta,
    color: COLORES[i % COLORES.length],
    puntos: base100
      ? r.curva.map(([t, v]) => [t, v / r.capital_inicial * 100])
      : r.curva,
  }));
  dibujar($("#grafico"), series, {
    alto: 300, log, formato: (v) => NUM.format(v),
    titulo: base100 ? "base 100" : "patrimonio",
  });

  const dd = R.map((r, i) => ({
    nombre: r.etiqueta, color: COLORES[i % COLORES.length],
    puntos: r.drawdown.map(([t, v]) => [t, v * 100]),
  }));
  dibujar($("#grafico-dd"), dd, {
    alto: 130, log: false, relleno: true, maxCero: true,
    formato: (v) => v.toFixed(0) + " %", titulo: "drawdown",
  });
}

function dibujar(cont, series, op) {
  const W = cont.clientWidth || 760, H = op.alto;
  const M = { arriba: 12, derecha: 14, abajo: 22, izquierda: 64 };
  const aw = Math.max(10, W - M.izquierda - M.derecha);
  const ah = Math.max(10, H - M.arriba - M.abajo);

  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  series.forEach((s) => s.puntos.forEach(([t, v]) => {
    if (t < x0) x0 = t; if (t > x1) x1 = t;
    if (v < y0) y0 = v; if (v > y1) y1 = v;
  }));
  if (!isFinite(x0)) return;
  if (op.maxCero) y1 = 0;
  if (op.log) { y0 = Math.max(y0, 1e-9); }
  const margen = (y1 - y0) * 0.06 || Math.abs(y1 || 1) * 0.06;
  let a = y0 - margen, b = y1 + (op.maxCero ? 0 : margen);
  if (op.log) { a = Math.max(y0 * 0.96, 1e-9); b = y1 * 1.04; }

  const tx = (t) => M.izquierda + (x1 === x0 ? 0 : (t - x0) / (x1 - x0)) * aw;
  const ty = op.log
    ? (v) => M.arriba + ah - (Math.log10(Math.max(v, 1e-9)) - Math.log10(a)) / (Math.log10(b) - Math.log10(a)) * ah
    : (v) => M.arriba + ah - (b === a ? 0.5 : (v - a) / (b - a)) * ah;

  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("width", W); svg.setAttribute("height", H);
  const el = (t, at) => { const e = document.createElementNS(ns, t); for (const k in at) e.setAttribute(k, at[k]); return e; };

  // rejilla + eje Y
  const marcasY = ticksY(a, b, op.log, 5);
  marcasY.forEach((v) => {
    const y = ty(v);
    if (y < M.arriba - 1 || y > M.arriba + ah + 1) return;
    svg.appendChild(el("line", { class: "malla", x1: M.izquierda, x2: W - M.derecha, y1: y, y2: y }));
    const tt = el("text", { class: "eje", x: M.izquierda - 8, y: y + 3.5, "text-anchor": "end" });
    tt.textContent = op.formato(v);
    svg.appendChild(tt);
  });

  // eje X
  const nX = Math.max(2, Math.min(7, Math.floor(aw / 130)));
  for (let i = 0; i <= nX; i++) {
    const t = x0 + (x1 - x0) * (i / nX), x = tx(t);
    const tt = el("text", { class: "eje", x, y: H - 6, "text-anchor": i === 0 ? "start" : i === nX ? "end" : "middle" });
    tt.textContent = etiquetaX(t, x1 - x0);
    svg.appendChild(tt);
  }

  // series
  series.forEach((s) => {
    let d = "";
    s.puntos.forEach(([t, v], i) => { d += (i ? "L" : "M") + tx(t).toFixed(1) + " " + ty(v).toFixed(1); });
    if (op.relleno) {
      const cero = ty(Math.min(0, b));
      const area = d + `L${tx(s.puntos[s.puntos.length - 1][0]).toFixed(1)} ${cero}L${tx(s.puntos[0][0]).toFixed(1)} ${cero}Z`;
      svg.appendChild(el("path", { d: area, fill: s.color, "fill-opacity": 0.10, stroke: "none" }));
    }
    svg.appendChild(el("path", { d, fill: "none", stroke: s.color, "stroke-width": 1.6,
                                 "stroke-linejoin": "round", "stroke-linecap": "round" }));
  });

  // interacción
  const cruz = el("line", { class: "cruz", y1: M.arriba, y2: M.arriba + ah, x1: 0, x2: 0, opacity: 0 });
  svg.appendChild(cruz);
  const capa = el("rect", { x: M.izquierda, y: M.arriba, width: aw, height: ah, fill: "transparent" });
  svg.appendChild(capa);

  capa.addEventListener("mousemove", (ev) => {
    const caja = svg.getBoundingClientRect();
    const px = (ev.clientX - caja.left) * (W / caja.width);
    const t = x0 + (px - M.izquierda) / aw * (x1 - x0);
    cruz.setAttribute("x1", px); cruz.setAttribute("x2", px); cruz.setAttribute("opacity", 1);
    const filas = series.map((s) => {
      const p = masCercano(s.puntos, t);
      return `<div><span class="punto" style="background:${s.color}"></span>${s.nombre}: <b>${op.formato(p[1])}</b></div>`;
    }).join("");
    globo(`<b>${fecha(masCercano(series[0].puntos, t)[0])}</b>${filas}`, ev.clientX, ev.clientY);
  });
  capa.addEventListener("mouseleave", () => { cruz.setAttribute("opacity", 0); ocultarGlobo(); });

  cont.innerHTML = "";
  cont.appendChild(svg);
}

function masCercano(puntos, t) {
  let lo = 0, hi = puntos.length - 1;
  while (lo < hi) {
    const m = (lo + hi) >> 1;
    if (puntos[m][0] < t) lo = m + 1; else hi = m;
  }
  if (lo > 0 && Math.abs(puntos[lo - 1][0] - t) < Math.abs(puntos[lo][0] - t)) lo--;
  return puntos[lo];
}

function ticksY(a, b, log, n) {
  if (log) {
    const out = [];
    for (let e = Math.floor(Math.log10(a)); e <= Math.ceil(Math.log10(b)); e++) {
      [1, 2, 5].forEach((m) => { const v = m * Math.pow(10, e); if (v >= a && v <= b) out.push(v); });
    }
    return out.length ? out : [a, b];
  }
  const paso = pasoBonito((b - a) / n);
  const out = [];
  for (let v = Math.ceil(a / paso) * paso; v <= b; v += paso) out.push(Number(v.toFixed(10)));
  return out;
}

function pasoBonito(x) {
  const e = Math.pow(10, Math.floor(Math.log10(Math.abs(x) || 1)));
  const f = x / e;
  // Sin el escalón de 2.5, un rango de 1015 salta de paso 200 a paso 500 y el
  // eje se queda con dos marcas.
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * e;
}

let _globo = null;
function globo(html, x, y) {
  if (!_globo) { _globo = crear("div", "globo"); document.body.appendChild(_globo); }
  _globo.innerHTML = html;
  _globo.style.display = "block";
  const an = _globo.offsetWidth, al = _globo.offsetHeight;
  _globo.style.left = Math.min(x + 14, window.innerWidth - an - 8) + "px";
  _globo.style.top = Math.max(8, Math.min(y - al - 12, window.innerHeight - al - 8)) + "px";
}
function ocultarGlobo() { if (_globo) _globo.style.display = "none"; }

/* ----------------------------------------------------------------- cableado */
function cablearBotones() {
  $("#b-backtest").onclick = () => lanzar("backtest");
  $("#b-comparar").onclick = () => lanzar("comparar");
  $("#b-ingest").onclick = () => lanzar("ingest");
  $("#b-validate").onclick = () => lanzar("validate");
  $("#b-info").onclick = () => lanzar("info");
  $("#b-limpiar").onclick = limpiarConsola;
  $("#escala-log").onchange = redibujar;
  $("#normalizar").onchange = redibujar;
  document.querySelectorAll("[data-todos]").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll("#simbolos input").forEach((i) => (i.checked = b.dataset.todos === "1"));
      contarSimbolos();
    };
  });
  let temporizador;
  window.addEventListener("resize", () => {
    clearTimeout(temporizador);
    temporizador = setTimeout(redibujar, 150);
  });
}

arrancar();
