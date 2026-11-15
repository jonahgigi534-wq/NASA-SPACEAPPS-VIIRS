// i18n.js: Spanish interface (beta), turned on with ?lang=es. English is the default.
// Static page text is translated by matching each text node against ES below; text built in
// JavaScript goes through I18N.t(). The server writes its plain-language sentences in Spanish when
// the request says lang: "es". Translations have not been reviewed by a native speaker yet.
const I18N = (() => {
  const params = new URLSearchParams(location.search);
  const es = params.get("lang") === "es";
  const ES = {
    "Skip to results": "Ir a los resultados",
    "Fire activity 2001 → today, from MODIS and VIIRS satellites, on one consistent scale":
      "Actividad de fuego de 2001 a hoy, de los satélites MODIS y VIIRS, en una escala coherente",
    "Fire calendar": "Calendario de fuego", "How it works": "Cómo funciona", "More checks": "Más pruebas",
    "For judges": "Para el jurado",
    "FireBridge is waking up": "FireBridge se está activando",
    "The server was asleep and is loading 25 years of fire data. This takes about two minutes; the page will open by itself.":
      "El servidor estaba en reposo y está cargando 25 años de datos de fuego. Tarda unos dos minutos; la página se abrirá sola.",
    "Starting…": "Iniciando…",
    "1. Choose an area": "1. Elija una zona", "Find a place": "Buscar un lugar", "Find": "Buscar",
    "Fire on the map": "Fuego en el mapa", "Off": "No", "Hotspots": "Focos", "vs normal": "vs lo normal",
    "All selected dates": "Todas las fechas elegidas",
    "Draw a": "Dibuje un", "rectangle": "rectángulo", "polygon": "polígono", "or": "o", "circle": "círculo",
    "with the tools on the map, or type coordinates below. Outlined boxes show where we have data.":
      "con las herramientas del mapa, o escriba coordenadas abajo. Los recuadros marcados muestran dónde hay datos.",
    "Big fire events (from the data)": "Grandes incendios (según los datos)",
    "Unusual right now": "Inusual ahora mismo",
    "Type coordinates instead": "Escribir coordenadas", "Box (decimal degrees)": "Recuadro (grados decimales)",
    "West": "Oeste", "South": "Sur", "East": "Este", "North": "Norte", "Use this box": "Usar este recuadro",
    "Point + radius": "Punto + radio", "Latitude": "Latitud", "Longitude": "Longitud", "Radius km": "Radio km",
    "Use this point": "Usar este punto",
    "2. Dates and settings": "2. Fechas y ajustes", "From": "Desde", "To": "Hasta",
    "Last 12 months": "Últimos 12 meses", "This year": "Este año", "Whole record": "Todo el registro",
    "Normal = years": "Normal = años", "to": "a",
    "Satellite record": "Registro satelital", "Harmonized": "Armonizado", "MODIS only": "Solo MODIS", "Raw VIIRS": "VIIRS sin ajustar",
    "Harmonized: VIIRS translated to the MODIS scale, so 2001–today is one consistent series.":
      "Armonizado: VIIRS traducido a la escala de MODIS, así 2001–hoy es una serie coherente.",
    "Measure": "Medida", "Hotspot count": "Número de focos", "Fire power (MW)": "Potencia de fuego (MW)",
    "Fire power (FRP) measures how intense fires were, not just how many. Harmonized record only.":
      "La potencia de fuego (FRP) mide la intensidad de los incendios, no solo cuántos hubo. Solo en el registro armonizado.",
    "3. Download": "3. Descargar", "Hotspots in this area (CSV)": "Focos en esta zona (CSV)",
    "Daily analytics table (CSV)": "Tabla diaria de análisis (CSV)", "Hotspots as GeoJSON": "Focos en GeoJSON",
    "Hotspots as KML": "Focos en KML", "Print a one-page briefing": "Imprimir un informe de una página",
    "Charts download as PNG with the": "Los gráficos se descargan en PNG con el botón",
    "button on each chart.": "de cada gráfico.",
    "Loading…": "Cargando…", "Copy link": "Copiar enlace", "Link copied": "Enlace copiado",
    "Hotspots in range": "Focos en el período", "of the median": "de la mediana", "Busiest month": "Mes con más fuego",
    "in range": "en el período", "Busiest year": "Año con más fuego", "on record": "del registro", "Fire season": "Temporada de incendios",
    "Choose an area to see its fire history.": "Elija una zona para ver su historia de incendios.",
    "Compare with another period": "Comparar con otro período", "Compare": "Comparar",
    "Burning calendar": "Calendario de quemas", "Patterns & critical periods": "Patrones y períodos críticos",
    "Now vs history": "Ahora vs historia", "Fires vs past": "Incendios vs pasado",
    "Hotspots per month, 2001 → today": "Focos por mes, 2001 → hoy", "Hotspots per week, 2001 → today": "Focos por semana, 2001 → hoy",
    "Months": "Meses", "Weeks": "Semanas", "Counts": "Cantidad",
    "Each square is one month. Click (or press Enter on) a month to see its days.":
      "Cada cuadro es un mes. Haga clic (o pulse Intro) en un mes para ver sus días.",
    "Each square is one week (Monday to Sunday). Click (or press Enter on) a week to see its days.":
      "Cada cuadro es una semana (de lunes a domingo). Haga clic (o pulse Intro) en una semana para ver sus días.",
    "no data": "sin datos", "provisional": "provisional", "your dates": "sus fechas", "Days": "Días",
    "Which months see the most fire": "Qué meses tienen más fuego",
    "Chance of an unusually busy month": "Probabilidad de un mes inusualmente activo",
    "(share of normal-years where the month was well above its normal; history, not a forecast)":
      "(proporción de años normales en que el mes estuvo muy por encima de lo normal; historia, no pronóstico)",
    "Which years had the most fire": "Qué años tuvieron más fuego",
    "This month so far": "Este mes hasta ahora", "of the median for these days": "de la mediana para estos días",
    "Day by day vs normal": "Día a día vs lo normal",
    "How the latest fire compares with every fire here since 2001": "Cómo se compara el último incendio con todos los de aquí desde 2001",
    "Loading fire clusters…": "Cargando grupos de incendios…",
    "Most recent fire clusters": "Grupos de incendios más recientes", "Largest fire clusters": "Grupos de incendios más grandes",
    "“Show” sets the dates to that fire and outlines it on the map.": "“Ver” pone las fechas de ese incendio y lo marca en el mapa.",
    "The satellite switch: raw vs harmonized": "El cambio de satélite: sin ajustar vs armonizado",
    "VIIRS (from 2012) sees many more hotspots than MODIS. Raw VIIRS jumps; the harmonized record continues on the MODIS scale.":
      "VIIRS (desde 2012) ve muchos más focos que MODIS. VIIRS sin ajustar salta; el registro armonizado sigue en la escala de MODIS.",
    "Data: NASA FIRMS active fires (MODIS C6.1, VIIRS 375 m S-NPP / NOAA-20 / NOAA-21). Built for NASA Space Apps 2026. Hotspots are satellite fire detections, not burned area.":
      "Datos: incendios activos de NASA FIRMS (MODIS C6.1, VIIRS 375 m S-NPP / NOAA-20 / NOAA-21). Hecho para NASA Space Apps 2026. Los focos son detecciones satelitales de fuego, no área quemada.",
    "Methods, validation and limitations": "Métodos, validación y limitaciones",
    "Find a place (town, park, county)…": "Buscar un lugar (pueblo, parque, condado)…",
    "Play the selected dates month by month": "Reproducir las fechas elegidas mes a mes", "Play month by month": "Reproducir mes a mes",
    "Copy a link to exactly this view": "Copiar un enlace a esta vista exacta", "Download PNG": "Descargar PNG",
    // text built in JavaScript
    "MODIS-scale hotspots": "focos en escala MODIS", "no satellite data for these dates": "sin datos satelitales para estas fechas",
    "MW, summed (MODIS scale)": "MW, suma (escala MODIS)", "Fire power in range": "Potencia de fuego en el período",
    "of the median (normal)": "de la mediana (normal)", "the median (normal)": "la mediana (normal)",
    "no normal to compare with": "sin un valor normal para comparar", "No data": "Sin datos",
    "can't compare with normal": "no se puede comparar con lo normal", "the median for these days": "la mediana para estos días",
    "Preparing…": "Preparando…", "Show": "Ver", "Dates": "Fechas", "Size rank": "Puesto por tamaño",
    "Your dates": "Sus fechas", "Other period": "Otro período", "Busiest month ": "Mes con más fuego",
    "Days with no data": "Días sin datos", "vs normal ": "vs lo normal", "Grouping hotspots into fire clusters…": "Agrupando focos en grupos de incendios…",
    "MODIS only: the original Terra + Aqua detections (1 km pixels). Consistent, but MODIS is ending in 2027.":
      "Solo MODIS: las detecciones originales de Terra + Aqua (píxeles de 1 km). Coherente, pero MODIS termina en 2027.",
    "Raw VIIRS: 375 m detections as reported, from 2012. Not comparable with MODIS years: it sees far more hotspots.":
      "VIIRS sin ajustar: detecciones de 375 m tal como se informan, desde 2012. No es comparable con los años MODIS: ve muchos más focos.",
    "Too few hotspots here to define a fire season.": "Hay muy pocos focos aquí para definir una temporada de incendios.",
    "No complete years to rank.": "No hay años completos para ordenar.",
    "Long-term trend: too few complete years to judge.": "Tendencia a largo plazo: muy pocos años completos para juzgar.",
  };
  const t = (s) => (es && ES[s] !== undefined ? ES[s] : s);

  function translatePage() {
    if (!es) return;
    document.documentElement.lang = "es";
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((n) => {
      const raw = n.nodeValue, key = raw.replace(/\s+/g, " ").trim();
      if (key && ES[key] !== undefined) n.nodeValue = raw.replace(raw.trim(), ES[key]);
    });
    document.querySelectorAll("[placeholder],[aria-label],[title]").forEach((el) => {
      ["placeholder", "aria-label", "title"].forEach((a) => {
        const v = el.getAttribute(a);
        if (v && ES[v] !== undefined) el.setAttribute(a, ES[v]);
      });
    });
  }

  // header link: switch language, keeping the view (#...) the address holds
  function addSwitch() {
    const nav = document.querySelector(".site-header nav");
    if (!nav) return;
    const a = document.createElement("a");
    const p = new URLSearchParams(location.search);
    if (es) p.delete("lang"); else p.set("lang", "es");
    const q = p.toString();
    a.href = `${location.pathname}${q ? "?" + q : ""}`;
    a.textContent = es ? "English" : "Español (beta)";
    a.lang = es ? "en" : "es";
    a.addEventListener("click", (e) => { e.preventDefault(); location.href = a.href + location.hash; });
    nav.appendChild(a);
  }

  translatePage();
  addSwitch();
  return { es, t, lang: es ? "es" : "en" };
})();
