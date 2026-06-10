function Panel({ title, subtitle, aside, children }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <strong>{title}</strong>
          {subtitle ? <span>{subtitle}</span> : null}
        </div>
        {aside ? <div>{aside}</div> : null}
      </div>
      <div className="panel-body">{children}</div>
    </section>
  );
}

function MetricCard({ label, value, detail }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <em>{detail}</em>
    </div>
  );
}

function BarChart({ rows, title, subtitle }) {
  return (
    <div className="chart-card">
      <div className="chart-title">
        <strong>{title}</strong>
        <span>{subtitle}</span>
      </div>
      <div className="bars">
        {rows.map((row) => (
          <div className="bar-row" key={row.label}>
            <span>{row.label}</span>
            <div className="bar-track" aria-hidden="true">
              <div className="bar-fill" style={{ width: `${Math.max(4, Math.min(100, row.value))}%` }}></div>
            </div>
            <b>{row.value}</b>
          </div>
        ))}
      </div>
    </div>
  );
}

function CoverageMatrix({ workbenches, columns }) {
  return (
    <div className="matrix">
      <div className="matrix-grid">
        <div className="matrix-cell head">工作台</div>
        {columns.map((column) => (
          <div className="matrix-cell head" key={column}>{column}</div>
        ))}
        {workbenches.map((desk) => (
          <React.Fragment key={desk.key}>
            <div className="matrix-cell head">{desk.title}</div>
            {desk.coverage.map((score, index) => (
              <div className={`matrix-cell fill-${score}`} key={`${desk.key}-${columns[index]}`}>
                {score === 0 ? "-" : score === 1 ? "辅助" : score === 2 ? "常用" : "核心"}
              </div>
            ))}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}

function LifecycleChart({ items }) {
  return (
    <div className="flow-chart">
      {items.map((item, index) => (
        <div className="flow-node" key={item.step}>
          <b>{String(index + 1).padStart(2, "0")}</b>
          <div>
            <strong>{item.step} · {item.area}</strong>
            <span>{item.result}</span>
          </div>
          <em>{index === items.length - 1 ? "交付" : "下一步"}</em>
        </div>
      ))}
    </div>
  );
}

function ValueScatter({ workbenches, activeKey, onSelect }) {
  return (
    <div className="scatter" role="img" aria-label="工作台价值与复杂度分布图">
      <span className="scatter-axis y">价值高</span>
      <span className="scatter-axis x">复杂度高</span>
      {workbenches.map((desk) => {
        const left = 10 + desk.complexity * 0.8;
        const top = 94 - desk.value * 0.78;
        return (
          <button
            className="scatter-dot"
            key={desk.key}
            style={{ left: `${left}%`, top: `${top}%` }}
            onClick={() => onSelect(desk.key)}
            aria-label={`查看${desk.title}`}
          >
            <i style={{ background: activeKey === desk.key ? "var(--accent-deep)" : "var(--accent)" }}></i>
            <span>{desk.title}</span>
          </button>
        );
      })}
    </div>
  );
}

function StarterPath({ steps, activeTitle }) {
  return (
    <div className="starter-path">
      {steps.map((step, index) => (
        <div className="path-step" key={step.title}>
          <b>{String(index + 1).padStart(2, "0")} · {step.desk}</b>
          <strong>{step.title}</strong>
          <span>{step.text}</span>
        </div>
      ))}
    </div>
  );
}

Object.assign(window, {
  Panel,
  MetricCard,
  BarChart,
  CoverageMatrix,
  LifecycleChart,
  ValueScatter,
  StarterPath
});
