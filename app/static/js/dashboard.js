// Gráficos do painel (Chart.js via CDN). Os dados vêm de /api/dashboard/*; as mesmas
// informações estão nas tabelas da página, então os gráficos são um complemento.
(() => {
  "use strict";

  const number = new Intl.NumberFormat("pt-BR");
  const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  const compact = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
  const formatters = {
    tenders: { full: (v) => `${number.format(v)} licitação(ões)`, tick: (v) => compact.format(v) },
    total_value: { full: (v) => brl.format(v), tick: (v) => `R$ ${compact.format(v)}` },
  };
  const charts = new Map(); // canvas -> {chart, items}

  function tokens() {
    const css = getComputedStyle(document.documentElement);
    const read = (name) => css.getPropertyValue(name).trim();
    return {
      mark: read("--chart-mark"),
      hover: read("--chart-mark-hover"),
      grid: read("--chart-grid"),
      axis: read("--chart-axis"),
      text: read("--muted"),
      surface: read("--surface"),
      ink: read("--text"),
    };
  }

  function config(canvas, items, t) {
    const kind = canvas.dataset.kind;
    const measure = canvas.dataset.measure;
    const format = formatters[measure];
    const horizontal = kind === "hbar";
    const values = items.map((item) => Number(item[measure]));
    const labels = items.map((item) => item.label + (item.partial ? " (parcial)" : ""));
    const valueAxis = {
      beginAtZero: true,
      grid: { color: t.grid, drawTicks: false },
      border: { display: false },
      ticks: { color: t.text, padding: 6, maxTicksLimit: 5, callback: (v) => format.tick(v),
               precision: measure === "tenders" ? 0 : undefined },
    };
    const categoryAxis = {
      grid: { display: false },
      border: { color: t.axis },
      ticks: {
        color: t.text,
        autoSkip: !horizontal,
        maxRotation: 0,
        // Nome longo é abreviado no eixo; o nome completo fica no tooltip e na tabela.
        callback(value) {
          const label = this.getLabelForValue(value);
          const max = this.chart.width < 480 ? 18 : 30;
          return label.length > max ? `${label.slice(0, max - 1)}…` : label;
        },
      },
    };
    const dataset = {
      data: values,
      backgroundColor: t.mark,
      hoverBackgroundColor: t.hover,
      borderColor: t.mark,
    };
    if (kind === "line") {
      Object.assign(dataset, {
        borderWidth: 2,
        pointRadius: 4,
        pointHoverRadius: 6,
        pointBorderColor: t.surface,
        pointBorderWidth: 2,
        pointHitRadius: 12,
        tension: 0,
        fill: { target: "origin", above: `${t.mark}1a` }, // ~10% de opacidade
      });
    } else {
      Object.assign(dataset, {
        maxBarThickness: 24,
        borderRadius: 4,
        borderSkipped: "start", // canto reto na linha de base, arredondado na ponta
      });
    }
    return {
      type: kind === "line" ? "line" : "bar",
      data: { labels, datasets: [dataset] },
      options: {
        indexAxis: horizontal ? "y" : "x",
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false, axis: horizontal ? "y" : "x" },
        scales: horizontal ? { x: valueAxis, y: categoryAxis } : { x: categoryAxis, y: valueAxis },
        plugins: {
          legend: { display: false }, // uma série só: o título do gráfico diz o que é
          tooltip: {
            backgroundColor: t.surface,
            titleColor: t.text,
            bodyColor: t.ink,
            borderColor: t.axis,
            borderWidth: 1,
            displayColors: false,
            padding: 10,
            bodyFont: { weight: "600" },
            callbacks: {
              label: (ctx) => format.full(ctx.parsed[horizontal ? "x" : "y"]),
              afterLabel: (ctx) => {
                const item = items[ctx.dataIndex];
                const other = measure === "tenders" ? "total_value" : "tenders";
                return formatters[other].full(Number(item[other]));
              },
            },
          },
        },
      },
    };
  }

  function draw(canvas, items) {
    const box = canvas.parentElement;
    if (canvas.dataset.kind === "hbar") box.style.height = `${Math.max(120, items.length * 30 + 40)}px`;
    charts.get(canvas)?.chart.destroy();
    const chart = new window.Chart(canvas, config(canvas, items, tokens()));
    charts.set(canvas, { chart, items });
  }

  function status(message) {
    const el = document.querySelector("[data-chart-status]");
    if (!el) return;
    el.textContent = message;
    el.hidden = !message;
  }

  async function load(root) {
    const canvases = [...root.querySelectorAll("canvas[data-chart]")].filter((c) => !charts.has(c));
    if (!canvases.length) return;
    if (!window.Chart) {
      status("Os gráficos não carregaram (sem acesso ao CDN do Chart.js). Os números estão nas tabelas.");
      document.querySelectorAll("details.data-table").forEach((d) => { d.open = true; });
      return;
    }
    const cache = new Map(); // o mesmo endpoint alimenta dois gráficos (mensal)
    const results = await Promise.allSettled(canvases.map(async (canvas) => {
      const url = canvas.dataset.endpoint;
      if (!cache.has(url)) {
        cache.set(url, fetch(url, { headers: { Accept: "application/json" } }).then((r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        }));
      }
      draw(canvas, (await cache.get(url)).items);
    }));
    const failed = results.filter((r) => r.status === "rejected").length;
    status(failed ? "Alguns gráficos não puderam ser carregados; os números estão nas tabelas." : "");
  }

  document.addEventListener("DOMContentLoaded", () => load(document));
  // Filtros trocam o conteúdo via HTMX: desenha de novo os gráficos que chegaram.
  document.addEventListener("htmx:afterSettle", () => {
    for (const [canvas, { chart }] of charts) {
      if (!canvas.isConnected) { chart.destroy(); charts.delete(canvas); }
    }
    load(document);
  });
  // Tema claro/escuro do sistema mudou: redesenha com as cores do novo tema.
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    for (const [canvas, { items }] of charts) draw(canvas, items);
  });
})();
