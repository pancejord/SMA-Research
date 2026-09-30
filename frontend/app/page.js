// File purpose: Display historical outfit rankings with simple trading-day and market filters.
"use client";

import { useState } from "react";

const timeframes = [...Array.from({ length: 55 }, (_, i) => `${i + 5}m`), "1h", "2h", "3h", "4h"];

// Format every report timestamp in Eastern Time, regardless of the browser's timezone.
function eastern(value, withTime = false) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", month: "short", day: "numeric", year: "numeric",
    ...(withTime ? { hour: "numeric", minute: "2-digit" } : {}),
  }).format(new Date(value));
}

// Render the filter form, report summary, and separate outfit/ticker/timeframe ranking rows.
export default function Dashboard() {
  const [filters, setFilters] = useState({ days: "5", top: "25", ticker: "", timeframe: "", through: "" });
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Clear old results when a filter changes so the table never suggests it uses unsent filters.
  function change(name, value) {
    setFilters((current) => ({ ...current, [name]: value }));
    setReport(null);
    setError("");
  }

  // Load one report on demand; the browser only talks to the local server route.
  async function loadRankings(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setReport(null);
    try {
      const response = await fetch(`/api/rankings?${new URLSearchParams(filters)}`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not load rankings.");
      setReport(data);
    } catch (failure) {
      setError(failure.message || "The dashboard could not reach the reporting server.");
    } finally {
      setLoading(false);
    }
  }

  const leader = report?.rows[0];
  return (
    <main>
      <header className="topbar"><a href="/" className="brand"><span className="brandmark">SMA</span> Research</a><span className="tag">Rankings dashboard</span></header>
      <section className="intro"><p className="eyebrow">OUTFIT RESEARCH</p><h1>Find the most-hit combinations.</h1><p>Compare outfits, tickers, and timeframes across completed trading sessions.</p></section>

      <form className="filters panel" onSubmit={loadRankings}>
        <fieldset disabled={loading}>
          <label>Trading days<select value={filters.days} onChange={(e) => change("days", e.target.value)}>{Array.from({ length: 19 }, (_, i) => <option key={i + 2} value={i + 2}>Last {i + 2} sessions</option>)}</select></label>
          <label>Ticker<input value={filters.ticker} onChange={(e) => change("ticker", e.target.value.toUpperCase())} placeholder="All tickers" maxLength={30} autoComplete="off" spellCheck={false} /></label>
          <label>Timeframe<select value={filters.timeframe} onChange={(e) => change("timeframe", e.target.value)}><option value="">All timeframes</option>{timeframes.map((tf) => <option key={tf}>{tf}</option>)}</select></label>
          <label>Through date <span className="optional">optional</span><input type="date" value={filters.through} onChange={(e) => change("through", e.target.value)} /></label>
          <label>Show<select value={filters.top} onChange={(e) => change("top", e.target.value)}>{[10, 25, 50, 100].map((n) => <option key={n} value={n}>Top {n}</option>)}</select></label>
          <button className="primary" type="submit">{loading ? "Loading…" : "Load rankings"}<span aria-hidden="true">↗</span></button>
        </fieldset>
        <p className="hint">Weekends and holidays are excluded. An unfinished trading session is not included.</p>
      </form>

      {error && <div className="error" role="alert"><strong>Rankings unavailable</strong><p>{error}</p><span>Configure credentials on the server, then select Load rankings to retry.</span></div>}

      <section className="summary" aria-label="Report summary">
        <article className="panel"><p className="eyebrow">LEADING OUTFIT</p><h2>{leader?.outfit || "—"}</h2><span>{leader ? `${leader.ticker} · ${leader.timeframe}` : "Based on the selected window"}</span></article>
        <article className="panel"><p className="eyebrow">LEADING HIT COUNT</p><h2>{leader ? leader.hits.toLocaleString() : "—"}</h2><span>Individual OHLC / SMA matches</span></article>
        <article className="panel"><p className="eyebrow">TRADING WINDOW</p><h2 className="window">{report ? `${eastern(report.start)} – ${eastern(report.end)}` : "No report loaded"}</h2><span>{report ? `${report.days} completed sessions · Eastern Time` : "Choose filters above to begin"}</span></article>
      </section>

      <section className="panel results" aria-busy={loading}>
        <div className="section-heading"><div><h2>Top rankings</h2><p>Each outfit, ticker, and timeframe is ranked separately.</p></div><span className="tag">{report ? `${report.rows.length} results` : "Stored hits"}</span></div>
        <div aria-live="polite">
          {loading ? <div className="empty"><span className="spinner" aria-hidden="true"/><h3>Reading stored hits…</h3><p>Calculating rankings for your trading window.</p></div> : !report ? <div className="empty"><div className="empty-symbol" aria-hidden="true">▥</div><h3>Your rankings will appear here</h3><p>Select a trading-day window and load rankings from InfluxDB.</p></div> : report.rows.length === 0 ? <div className="empty"><h3>No matching hits found</h3><p>Try a longer window or fewer filters. Preloaded candles alone do not create hits.</p></div> :
            <div className="table-scroll"><table><caption className="sr-only">Top SMA outfit combinations by hit count</caption><thead><tr><th scope="col">Rank</th><th scope="col">Outfit</th><th scope="col">Ticker</th><th scope="col">Timeframe</th><th scope="col" className="hits">Hits</th><th scope="col">Latest hit · ET</th></tr></thead><tbody>{report.rows.map((row, i) => <tr key={`${row.outfit}/${row.ticker}/${row.timeframe}`}><td><span className={`rank ${i === 0 ? "first" : ""}`}>{i + 1}</span></td><td className="outfit">{row.outfit}</td><td><span className="ticker">{row.ticker}</span></td><td>{row.timeframe}</td><td className="hits"><strong>{row.hits.toLocaleString()}</strong><div className="bar" aria-hidden="true"><span style={{ width: `${row.hits / leader.hits * 100}%` }}/></div></td><td className="timestamp">{eastern(row.last_hit, true)}</td></tr>)}</tbody></table></div>}
        </div>
        <footer className="table-footer"><span>Highest hit count first. Ties use the most recent hit.</span>{report && <span>Version {report.version} · Updated {eastern(report.generated_at, true)} ET</span>}</footer>
      </section>
      <p className="footnote">Counts reflect available stored hits, not guaranteed data coverage. This dashboard reads data only; it does not start collection.</p>
    </main>
  );
}
