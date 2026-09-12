"use strict";
/* Vista «En vivo»: lanzar agentes, verlos operar y seguir el resultado día a día.
   Reutiliza $, crear, dibujar, NUM y COLORES de app.js. */

const V = {
  catalogo: null,
  agentes: [],
  actual: null,       // nombre del agente seleccionado
  datos: null,        // último detalle recibido
  refresco: null,
  divisa: "EUR",
};

const eur = (v, d = 2) =>
  (v === null || v === undefined || Number.isNaN(v)) ? "—"
    : new Intl.NumberFormat("es-ES", { minimumFractionDigits: d, maximumFractionDigits: d }).format(v);
// Se firma sobre el valor ya redondeado: si no, un −0,0000001 sale como «−0,00».
const firmado = (v, d = 2) => {
  const r = Number((v || 0).toFixed(d)) || 0;   // «|| 0» también neutraliza el -0
  return (r > 0 ? "+" : "") + eur(r, d);
};
const hora = (ms) => new Date(ms).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
// Menos de medio céntimo no es ni ganancia ni pérdida: es ruido de coma flotante.
const signo = (v) => (v > 0.005 ? "pos" : v < -0.005 ? "neg" : "apagado");
const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;
const pc = (v, d = 2) => ((Number(((v || 0) * 100).toFixed(d)) || 0).toFixed(d) + " %");

/* ------------------------------------------------------------- pestañas */
function cablearPestanas() {
  document.querySelectorAll(".pestanas button").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll(".pestanas button").forEach((o) =>
        o.setAttribute("aria-pressed", String(o === b)));
      $("#vista-vivo").classList.toggle("oculto", b.dataset.vista !== "vivo");
      $("#vista-lab").classList.toggle("oculto", b.dataset.vista !== "lab");
      if (b.dataset.vista === "vivo") { refrescar(); arrancarRefresco(); }
      else { pararRefresco(); redibujar(); }
    };
  });
}

/* --------------------------------------------------------------- arranque */
async function iniciarVivo() {
  cablearPestanas();
  let d;
  try { d = await (await pedir("/api/vivo")).json(); }
  catch (e) { return; }
  V.catalogo = d.catalogo;
  V.agentes = d.agentes;

  const f = $("#v-fuente");
  d.catalogo.fuentes.forEach((x) =>
    f.appendChild(new Option({ binance: "Binance · cripto en tiempo real",
                               yahoo: "Yahoo · acciones y ETFs",
                               sintetica: "Ensayo · mercado generado, rápido" }[x.id] || x.id, x.id)));
  f.value = "sintetica";
  f.onchange = pintarFuente;

  const i = $("#v-intervalo");
  d.catalogo.intervalos.forEach((x) => i.appendChild(new Option(x, x)));
  i.value = "15m";

  const e = $("#v-estrategia");
  d.catalogo.estrategias.forEach((x) => e.appendChild(new Option(x.id.replace(/_/g, " "), x.id)));
  e.value = "tendencia_vol";
  e.onchange = pintarEstrategiaVivo;

  pintarFuente();
  pintarEstrategiaVivo();
  cablearVivo();
  pintarLista();
  if (V.agentes.length) seleccionar((V.agentes.find((a) => a.operando) || V.agentes[0]).nombre);
  else $("#form-nuevo").classList.remove("oculto");
  arrancarRefresco();
}

function pintarFuente() {
  const id = $("#v-fuente").value;
  const x = V.catalogo.fuentes.find((f) => f.id === id);
  $("#v-nota-fuente").textContent = x ? x.descripcion : "";
  $("#v-ensayo").classList.toggle("oculto", id !== "sintetica");

  const ejemplos = {
    binance: "Ejemplos: BTCEUR, ETHEUR, BTCUSDT, SOLEUR.",
    yahoo: "Ejemplos: AAPL, MSFT, SPY, SAN.MC, IWDA.AS.",
    sintetica: "El símbolo es sólo una etiqueta: el mercado lo genera el propio agente.",
  };
  $("#v-nota-simbolo").textContent = ejemplos[id] || "";
  if (id === "yahoo" && $("#v-simbolo").value === "BTCEUR") $("#v-simbolo").value = "SPY";
  if (id === "binance" && $("#v-simbolo").value === "SPY") $("#v-simbolo").value = "BTCEUR";
}

function pintarEstrategiaVivo() {
  const x = V.catalogo.estrategias.find((s) => s.id === $("#v-estrategia").value);
  $("#v-nota-estrategia").textContent = x ? x.descripcion : "";
}

/* ------------------------------------------------------------------ lista */
function pintarLista() {
  const c = $("#lista-agentes");
  c.innerHTML = "";
  if (!V.agentes.length) {
    c.appendChild(crear("p", "nota", "Ninguno todavía."));
    return;
  }
  V.agentes.forEach((a) => {
    const b = crear("button", "agente" + (a.nombre === V.actual ? " elegido" : ""));
    const punto = crear("i", "punto " + (a.muerto ? "muerto" : a.operando ? "operando" : "pausado"));
    const izq = crear("div", "agente-izq");
    izq.append(punto, crear("span", null, a.nombre));
    const pnl = (a.equity != null && a.capital) ? a.equity / a.capital - 1 : null;
    const der = crear("span", "agente-pnl " + (pnl === null ? "apagado" : signo(pnl)),
      pnl === null ? "—" : (Number((pnl * 100).toFixed(1)) > 0 ? "+" : "") + pc(pnl, 1));
    b.append(izq, der);
    b.onclick = () => seleccionar(a.nombre);
    c.appendChild(b);
  });
}

function seleccionar(nombre) {
  V.actual = nombre;
  $("#form-nuevo").classList.add("oculto");
  pintarLista();
  refrescar();
}

/* -------------------------------------------------------------- refresco */
function arrancarRefresco() {
  pararRefresco();
  V.refresco = setInterval(refrescar, 3000);
}
function pararRefresco() { if (V.refresco) { clearInterval(V.refresco); V.refresco = null; } }

async function refrescar() {
  try {
    const lista = await (await pedir("/api/vivo")).json();
    V.agentes = lista.agentes || [];
    if (V.actual && !V.agentes.some((a) => a.nombre === V.actual)) V.actual = null;
    pintarLista();
  } catch (e) { return; }

  if (!V.actual) {
    ["#cab-agente", "#kpis", "#caja-curva", "#caja-dias", "#caja-ops-vivo", "#caja-diario"]
      .forEach((s) => $(s).classList.add("oculto"));
    $("#vivo-vacio").classList.toggle("oculto", V.agentes.length > 0);
    return;
  }
  $("#vivo-vacio").classList.add("oculto");

  let d;
  try { d = await (await pedir("/api/vivo/" + encodeURIComponent(V.actual))).json(); }
  catch (e) { return; }
  if (d.error) return;
  V.datos = d;
  V.divisa = d.divisa || "EUR";
  pintarAgente(d);
}

/* --------------------------------------------------------------- detalle */
function pintarAgente(d) {
  $("#cab-agente").classList.remove("oculto");
  $("#titulo-agente").textContent = d.nombre;

  if (d.arrancando) {
    $("#linea-estado").innerHTML =
      `<span class="insignia trabajando">arrancando</span> descargando el histórico
       inicial; el primer latido llega en unos segundos.`;
    ["#kpis", "#caja-curva", "#caja-dias", "#caja-ops-vivo"].forEach((s) => $(s).classList.add("oculto"));
    if (d.salida) { $("#caja-diario").classList.remove("oculto"); $("#diario").textContent = d.salida; }
    botones(d);
    return;
  }

  const c = d.config || {};
  const estadoIns = d.muerto
    ? `<span class="insignia muerto">† muerto</span>`
    : d.operando ? `<span class="insignia operando">● operando</span>`
                 : `<span class="insignia pausado">‖ pausado</span>`;
  let linea = `${estadoIns} <b>${d.simbolo}</b> · ${c.estrategia} · vela ${c.intervalo}
    · ${plural(d.ticks, "latido", "latidos")}`;
  if (d.muerto) {
    linea += ` — causa: <b>${d.causa_muerte}</b>. ${d.detalle_muerte || ""}`;
  } else if (d.operando && d.segundos_desde_tick != null) {
    const falta = Math.max(0, d.intervalo_seg - d.segundos_desde_tick);
    linea += ` · próximo latido en ~${falta > 90 ? Math.round(falta / 60) + " min" : Math.round(falta) + " s"}`;
  } else if (!d.operando) {
    linea += ` — pausado: su estado está guardado y puede continuar donde lo dejó.`;
  }
  $("#linea-estado").innerHTML = linea;
  botones(d);

  pintarKpis(d);
  pintarCurva(d);
  pintarDias(d);
  pintarOpsVivo(d);
  pintarDiario(d);
}

function botones(d) {
  $("#b-parar").classList.toggle("oculto", !d.operando);
  $("#b-continuar").classList.toggle("oculto", !!d.operando || !!d.muerto);
  $("#b-cero").classList.toggle("oculto", !!d.operando);
  $("#b-borrar").classList.toggle("oculto", !!d.operando);
}

function pintarKpis(d) {
  const k = $("#kpis");
  k.classList.remove("oculto");
  k.innerHTML = "";
  const tarjetas = [
    { t: "Patrimonio", v: eur(d.equity) + " " + d.divisa,
      s: `empezó con ${eur(d.capital_inicial)}`, c: signo(d.pnl_total) },
    { t: "Resultado total", v: firmado(d.pnl_total) + " " + d.divisa,
      s: pc(d.pnl_total_pct) + " desde el inicio", c: signo(d.pnl_total) },
    { t: "Hoy", v: d.ticks_hoy ? firmado(d.pnl_hoy) + " " + d.divisa : "—",
      s: d.ticks_hoy ? pc(d.pnl_hoy_pct) + " · " + plural(d.ticks_hoy, "latido", "latidos") + " hoy"
                     : "todavía sin latidos hoy", c: d.ticks_hoy ? signo(d.pnl_hoy) : "apagado" },
    { t: "Posición", v: d.posicion.cantidad > 1e-12 ? pc(d.exposicion, 0) + " invertido" : "fuera",
      s: d.posicion.cantidad > 1e-12
         ? `${eur(d.posicion.cantidad, 6)} ${d.simbolo} · medio ${eur(d.posicion.precio_medio, 4)}`
         : "todo en caja", c: "" },
    { t: "Caja", v: eur(d.caja) + " " + d.divisa,
      s: `comisiones ${eur(d.comisiones)} · coste de vida ${eur(d.coste_vida)}`, c: "" },
    { t: "Caída desde máximo", v: pc(d.drawdown),
      s: `muere al ${pc(d.max_drawdown_permitido, 0)} · o si baja de ${eur(d.umbral_ruina)}`,
      c: d.drawdown > 0.0001 ? "neg" : "apagado" },
  ];
  tarjetas.forEach((x) => {
    const e = crear("div", "kpi");
    e.append(crear("span", "kpi-t", x.t), crear("span", "kpi-v " + x.c, x.v), crear("span", "kpi-s", x.s));
    k.appendChild(e);
  });
}

function pintarCurva(d) {
  const caja = $("#caja-curva");
  if (!d.serie || d.serie.length < 2) {
    caja.classList.add("oculto");
    return;
  }
  caja.classList.remove("oculto");
  $("#apunte-curva").textContent =
    `${d.serie.length} muestras · desde ${new Date(d.serie[0][0]).toLocaleString("es-ES")}`;
  const base = [[d.serie[0][0], d.capital_inicial], [d.serie[d.serie.length - 1][0], d.capital_inicial]];
  // Al principio el recorrido son céntimos: con 0 decimales el eje repetiría
  // «1000» cuatro veces. Los decimales salen del recorrido real de la serie.
  const valores = d.serie.map((p) => p[1]).concat([d.capital_inicial]);
  const recorrido = Math.max(...valores) - Math.min(...valores);
  const decimales = recorrido >= 100 ? 0 : recorrido >= 5 ? 1 : 2;

  dibujar($("#curva-vivo"), [
    { nombre: "capital inicial", color: "#6b7a8c", puntos: base },
    { nombre: "patrimonio", color: d.pnl_total >= 0 ? "#2fbf87" : "#e5606b", puntos: d.serie },
  ], { alto: 260, log: false, formato: (v) => eur(v, decimales), titulo: "patrimonio" });
}

function pintarDias(d) {
  const caja = $("#caja-dias");
  if (!d.dias || !d.dias.length) { caja.classList.add("oculto"); return; }
  caja.classList.remove("oculto");
  const t = $("#tabla-dias");
  t.innerHTML = "";
  const cab = ["día", "patrimonio al cierre", "resultado", "%", "mínimo", "máximo", "latidos"];
  const thead = crear("thead"), trh = crear("tr");
  cab.forEach((h, i) => trh.appendChild(crear("th", i ? "num" : null, h)));
  thead.appendChild(trh); t.appendChild(thead);
  const tb = crear("tbody");
  d.dias.slice().reverse().forEach((x) => {
    const tr = crear("tr");
    tr.appendChild(crear("td", null, x.dia));
    tr.appendChild(crear("td", "num", eur(x.cierre)));
    tr.appendChild(crear("td", "num " + signo(x.pnl), firmado(x.pnl)));
    tr.appendChild(crear("td", "num " + signo(x.pnl), pc(x.pnl_pct)));
    tr.appendChild(crear("td", "num apagado", eur(x.minimo)));
    tr.appendChild(crear("td", "num apagado", eur(x.maximo)));
    tr.appendChild(crear("td", "num apagado", x.ticks));
    tb.appendChild(tr);
  });
  t.appendChild(tb);
}

function pintarOpsVivo(d) {
  const caja = $("#caja-ops-vivo");
  if (!d.operaciones || !d.operaciones.length) { caja.classList.add("oculto"); return; }
  caja.classList.remove("oculto");
  $("#apunte-ops").textContent = `(${d.n_operaciones} en total · ${d.operaciones.length} mostradas)`;
  const t = $("#tabla-ops-vivo");
  t.innerHTML = "";
  const cab = ["fecha", "lado", "cantidad", "precio", "importe", "comisión", "realizado", "motivo"];
  const thead = crear("thead"), trh = crear("tr");
  cab.forEach((h, i) => trh.appendChild(crear("th", (i >= 2 && i <= 6) ? "num" : null, h)));
  thead.appendChild(trh); t.appendChild(thead);
  const tb = crear("tbody");
  d.operaciones.slice().reverse().forEach((o) => {
    const tr = crear("tr");
    const f = new Date((o.ts || 0) * 1000);
    tr.appendChild(crear("td", null, f.toLocaleString("es-ES", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })));
    tr.appendChild(crear("td", o.lado === "compra" ? "pos" : "neg", o.lado));
    tr.appendChild(crear("td", "num", eur(o.cantidad, 6)));
    tr.appendChild(crear("td", "num", eur(o.precio, 4)));
    tr.appendChild(crear("td", "num", eur((o.cantidad || 0) * (o.precio || 0))));
    tr.appendChild(crear("td", "num apagado", eur(o.comision, 4)));
    tr.appendChild(crear("td", "num " + (o.realizado == null ? "apagado" : signo(o.realizado)),
      o.realizado == null ? "—" : firmado(o.realizado)));
    tr.appendChild(crear("td", "apagado", o.motivo || ""));
    tb.appendChild(tr);
  });
  t.appendChild(tb);
}

const LEGIBLE = {
  nacimiento: (e) => `● nace con ${eur(e.capital)} ${e.divisa || ""} sobre ${e.simbolo} — ${e.estrategia}`,
  operacion: (e) => `${e.lado === "compra" ? "▲" : "▼"} ${e.lado} ${eur(e.cantidad, 6)} ${e.simbolo} @ ${eur(e.precio, 4)} · ${e.motivo || ""}`,
  rechazo: (e) => `· orden rechazada (${e.lado}): ${e.motivo}`,
  muerte: (e) => `✝ MUERTE [${e.causa}] ${e.detalle || ""} · patrimonio final ${eur(e.equity)}`,
};

function pintarDiario(d) {
  const caja = $("#caja-diario");
  if (!d.eventos || !d.eventos.length) { caja.classList.add("oculto"); return; }
  caja.classList.remove("oculto");
  const p = $("#diario");
  p.innerHTML = "";
  d.eventos.forEach((e) => {
    const fn = LEGIBLE[e.tipo];
    const cls = e.tipo === "muerte" ? "l-error" : e.tipo === "rechazo" ? "l-warning"
              : e.tipo === "operacion" ? "l-hito" : null;
    p.appendChild(crear("div", cls, `${hora(e.ts * 1000)}  ${fn ? fn(e) : e.tipo}`));
  });
  p.scrollTop = p.scrollHeight;
}

/* ------------------------------------------------------------- acciones */
function formulario() {
  return {
    nombre: $("#v-nombre").value.trim(),
    capital: Number($("#v-capital").value),
    divisa: $("#v-divisa").value.trim() || "EUR",
    simbolo: $("#v-simbolo").value.trim(),
    intervalo: $("#v-intervalo").value,
    fuente: $("#v-fuente").value,
    estrategia: $("#v-estrategia").value,
    ruina: Number($("#v-ruina").value),
    max_dd: Number($("#v-maxdd").value),
    stop_loss: Number($("#v-stop").value),
    trailing_stop: Number($("#v-trailing").value),
    max_exposicion: Number($("#v-exposicion").value),
    banda: Number($("#v-banda").value),
    comision_bps: Number($("#v-comision").value),
    slippage_bps: Number($("#v-slippage").value),
    coste_vida: Number($("#v-costevida").value),
    minimo_operacion: Number($("#v-minimo").value),
    velas: Number($("#v-velas").value),
    paso_seg: Number($("#v-paso").value),
    reencarnar: $("#v-reencarnar").checked,
  };
}

async function postear(ruta, cuerpo) {
  const r = await (await pedir(ruta, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cuerpo),
  })).json();
  return r;
}

function cablearVivo() {
  $("#b-nuevo").onclick = () => {
    $("#form-nuevo").classList.remove("oculto");
    $("#v-error").textContent = "";
    $("#v-nombre").focus();
  };
  $("#b-cancelar-nuevo").onclick = () => $("#form-nuevo").classList.add("oculto");

  $("#form-nuevo").onsubmit = async (ev) => {
    ev.preventDefault();
    $("#v-error").textContent = "Arrancando…";
    const r = await postear("/api/vivo/arrancar", formulario());
    if (r.error) { $("#v-error").textContent = r.error; return; }
    $("#v-error").textContent = "";
    $("#form-nuevo").classList.add("oculto");
    $("#v-reencarnar").checked = false;
    seleccionar(r.nombre);
  };

  $("#b-parar").onclick = async () => { await postear("/api/vivo/parar", { nombre: V.actual }); refrescar(); };

  $("#b-continuar").onclick = async () => {
    const c = (V.datos && V.datos.config) || {};
    const r = await postear("/api/vivo/arrancar", Object.assign(formulario(), {
      nombre: V.actual, simbolo: c.simbolo, intervalo: c.intervalo,
      estrategia: c.estrategia, capital: c.capital, divisa: c.divisa,
      fuente: (V.datos && V.datos.fuente) || $("#v-fuente").value, reencarnar: false,
    }));
    if (r.error) alert(r.error);
    refrescar();
  };

  $("#b-cero").onclick = async () => {
    if (!confirm(`¿Empezar de cero «${V.actual}»?\n\nSe borran su estado, su historial y su lápida. No se puede deshacer.`)) return;
    const c = (V.datos && V.datos.config) || {};
    const r = await postear("/api/vivo/arrancar", Object.assign(formulario(), {
      nombre: V.actual, simbolo: c.simbolo, intervalo: c.intervalo,
      estrategia: c.estrategia, capital: c.capital, divisa: c.divisa,
      fuente: (V.datos && V.datos.fuente) || $("#v-fuente").value, reencarnar: true,
    }));
    if (r.error) alert(r.error);
    refrescar();
  };

  $("#b-borrar").onclick = async () => {
    if (!confirm(`¿Borrar «${V.actual}» y todo su historial?\n\nNo se puede deshacer.`)) return;
    const r = await postear("/api/vivo/borrar", { nombre: V.actual });
    if (r.error) { alert(r.error); return; }
    V.actual = null;
    refrescar();
  };

  let tmp;
  window.addEventListener("resize", () => {
    clearTimeout(tmp);
    tmp = setTimeout(() => { if (V.datos) pintarCurva(V.datos); }, 150);
  });
}

iniciarVivo();
