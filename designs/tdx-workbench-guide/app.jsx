const { useMemo, useState } = React;

function RouteCards({ role, workbenchMap, onSelect }) {
  return (
    <div className="route-list">
      <div className="route-card">
        <strong>{role.label}的建议路径</strong>
        <span>{role.promise}</span>
        <div className="chips">
          {role.route.map((key) => (
            <button className="chip" key={key} onClick={() => onSelect(key)}>
              {workbenchMap.get(key).title}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function WorkbenchDetail({ desk, onSelect }) {
  return (
    <div className="workbench-detail">
      <div className="detail-title">
        <h2>{desk.title}</h2>
        <p>{desk.beginner}</p>
      </div>

      <div className="fact-grid">
        <div className="fact-card">
          <span>什么时候用</span>
          <strong>{desk.when}</strong>
        </div>
        <div className="fact-card">
          <span>主要输入</span>
          <strong>{desk.inputs.join("、")}</strong>
        </div>
        <div className="fact-card">
          <span>主要产出</span>
          <strong>{desk.outputs.join("、")}</strong>
        </div>
      </div>

      <div className="grid two">
        <Panel title="第一次操作顺序" subtitle="照这个顺序点，先看结果再调参数">
          <div className="checklist">
            {desk.checklist.map((item, index) => (
              <div className="check-item" key={item}>
                <span className="check-number">{index + 1}</span>
                <div>
                  <strong>{item}</strong>
                  <span>{index === 0 ? "先确认入口与基础条件。" : index === 1 ? "再看中间结果是否符合预期。" : "最后再进入下一工作台。"}</span>
                </div>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="模块强度图" subtitle="数值是面向新手的相对权重">
          <BarChart rows={desk.chart} title={`${desk.title}的关键动作`} subtitle="越高越常用" />
        </Panel>
      </div>

      {desk.subtools ? (
        <Panel title="研究工具子模块" subtitle="先按问题选模块，不要一开始就调高级参数">
          <div className="subtool-list">
            {desk.subtools.map((tool, index) => (
              <div className="subtool" key={tool.name}>
                <span className="check-number">{index + 1}</span>
                <div>
                  <strong>{tool.name}</strong>
                  <span>{tool.use}</span>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      ) : null}

      <Panel title="容易误解的地方" subtitle="新手最常踩的坑">
        <div className="empty-note">{desk.risk}</div>
      </Panel>
    </div>
  );
}

function Overview({ data, activeDesk, selectedRole, workbenchMap, onSelect }) {
  const metrics = [
    { label: "主工作台", value: data.workbenches.length, detail: "覆盖数据、研究、任务、设置" },
    { label: "研究子模块", value: data.workbenches.find((desk) => desk.key === "research").subtools.length, detail: "从相似度到市场风偏" },
    { label: "新手路径", value: data.starterSteps.length, detail: "按顺序跑通第一轮" },
    { label: "当前建议", value: selectedRole.route.length, detail: selectedRole.label }
  ];

  return (
    <div className="grid">
      <section className="hero-map" data-screen-label="overview">
        <div className="intro">
          <div>
            <h2>从“数据在哪里”到“今天该看什么”，一页看懂 TDX 工作台。</h2>
            <p>
              这不是功能清单，而是一条操作路线：先让路径和缓存可信，再用下载任务补齐数据，
              之后进入研究工具和 AI 工作台生成可复核结论。没接触过的人也可以从左到右跑一遍。
            </p>
          </div>
          <StarterPath steps={data.starterSteps} />
          <div className="metric-strip">
            {metrics.map((item) => (
              <MetricCard key={item.label} label={item.label} value={item.value} detail={item.detail} />
            ))}
          </div>
        </div>

        <Panel title="按你的角色走" subtitle="点击路径里的工作台可直接跳转">
          <RouteCards role={selectedRole} workbenchMap={workbenchMap} onSelect={onSelect} />
          <div style={{ height: 12 }}></div>
          <LifecycleChart items={data.lifecycle} />
        </Panel>
      </section>

      <section className="grid two">
        <WorkbenchDetail desk={activeDesk} onSelect={onSelect} />
        <div className="grid">
          <Panel title="工作台覆盖矩阵" subtitle="看每个工作台负责准备、采集、研究还是解释">
            <CoverageMatrix workbenches={data.workbenches} columns={data.matrixColumns} />
          </Panel>
          <Panel title="价值 / 复杂度" subtitle="右上角通常是高价值但需要更多前置条件">
            <ValueScatter workbenches={data.workbenches} activeKey={activeDesk.key} onSelect={onSelect} />
          </Panel>
        </div>
      </section>
    </div>
  );
}

function MapView({ data, onSelect }) {
  return (
    <div className="grid two" data-screen-label="map">
      <Panel title="完整数据链路" subtitle="按这个顺序排查，大多数问题都能定位">
        <LifecycleChart items={data.lifecycle} />
      </Panel>
      <Panel title="覆盖矩阵" subtitle="深色代表该工作台是核心入口">
        <CoverageMatrix workbenches={data.workbenches} columns={data.matrixColumns} />
      </Panel>
      <Panel title="工作台关系" subtitle="点击散点切换左侧选中的工作台">
        <ValueScatter workbenches={data.workbenches} activeKey="research" onSelect={onSelect} />
      </Panel>
      <Panel title="新手判断规则" subtitle="不知道点哪里时，按问题类型选">
        <div className="route-list">
          <div className="route-card">
            <strong>数据缺不缺</strong>
            <span>去缓存资产看最近日期，再去下载任务预览缺口。</span>
          </div>
          <div className="route-card">
            <strong>任务为什么卡住</strong>
            <span>去执行记录看后台状态、错误和写入结果。</span>
          </div>
          <div className="route-card">
            <strong>市场现在强不强</strong>
            <span>去研究工具里的市场风险偏好，看 RAI、热力图和资金回流候选。</span>
          </div>
          <div className="route-card">
            <strong>怎么写成结论</strong>
            <span>先保存研究快照，再让 AI 工作台基于证据生成解释。</span>
          </div>
        </div>
      </Panel>
    </div>
  );
}

function ChartView({ data, activeDesk, onSelect }) {
  return (
    <div className="grid" data-screen-label="charts">
      <section className="grid three">
        {data.workbenches.map((desk) => (
          <Panel
            key={desk.key}
            title={desk.title}
            subtitle={desk.subtitle}
            aside={<button className="kbd" onClick={() => onSelect(desk.key)}>查看</button>}
          >
            <BarChart rows={desk.chart} title="关键动作分布" subtitle="相对权重" />
          </Panel>
        ))}
      </section>
      <section className="grid two">
        <Panel title="当前选中工作台" subtitle={activeDesk.subtitle}>
          <div className="workbench-detail">
            <div className="detail-title">
              <h2>{activeDesk.title}</h2>
              <p>{activeDesk.beginner}</p>
            </div>
            <div className="fact-grid">
              <div className="fact-card">
                <span>什么时候用</span>
                <strong>{activeDesk.when}</strong>
              </div>
              <div className="fact-card">
                <span>主要动作</span>
                <strong>{activeDesk.actions.join("、")}</strong>
              </div>
              <div className="fact-card">
                <span>注意点</span>
                <strong>{activeDesk.risk}</strong>
              </div>
            </div>
          </div>
        </Panel>
        <Panel title="价值 / 复杂度总览" subtitle="越靠上越值得优先掌握">
          <ValueScatter workbenches={data.workbenches} activeKey={activeDesk.key} onSelect={onSelect} />
        </Panel>
      </section>
    </div>
  );
}

function App() {
  const data = window.GUIDE_DATA;
  const [activeKey, setActiveKey] = useState("dashboard");
  const [roleKey, setRoleKey] = useState("beginner");
  const [view, setView] = useState("guide");

  const workbenchMap = useMemo(() => new Map(data.workbenches.map((desk) => [desk.key, desk])), [data.workbenches]);
  const activeDesk = workbenchMap.get(activeKey) || data.workbenches[0];
  const selectedRole = data.roles.find((role) => role.key === roleKey) || data.roles[0];

  return (
    <div className="app">
      <aside className="rail">
        <div className="brand">
          <div className="brand-mark">TDX</div>
          <div>
            <strong>工作台使用说明</strong>
            <span>面向第一次接触的人，把入口、顺序、产出讲清楚。</span>
          </div>
        </div>

        <div className="role-card">
          <label htmlFor="role">选择你的使用场景</label>
          <select id="role" value={roleKey} onChange={(event) => setRoleKey(event.target.value)}>
            {data.roles.map((role) => (
              <option value={role.key} key={role.key}>{role.label}</option>
            ))}
          </select>
          <span className="hint">{selectedRole.promise}</span>
        </div>

        <nav className="nav-list" aria-label="工作台导航">
          {data.workbenches.map((desk) => (
            <button
              className={`nav-button ${activeKey === desk.key ? "active" : ""}`}
              key={desk.key}
              onClick={() => setActiveKey(desk.key)}
            >
              <span>
                <strong>{desk.title}</strong>
                <span>{desk.subtitle}</span>
              </span>
              <span className="nav-score">{desk.value}</span>
            </button>
          ))}
        </nav>

        <div className="rail-foot">
          使用方法：先按角色走一遍建议路径，再回到左侧选择具体工作台，看“什么时候用、怎么点、产出什么”。
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>{activeDesk.title} · {activeDesk.subtitle}</h1>
            <p>{activeDesk.when}</p>
          </div>
          <div className="view-switch" aria-label="页面模式">
            {[
              ["guide", "新手说明"],
              ["map", "流程地图"],
              ["charts", "图表总览"]
            ].map(([key, label]) => (
              <button className={view === key ? "active" : ""} key={key} onClick={() => setView(key)}>
                {label}
              </button>
            ))}
          </div>
        </header>

        {view === "guide" ? (
          <Overview data={data} activeDesk={activeDesk} selectedRole={selectedRole} workbenchMap={workbenchMap} onSelect={setActiveKey} />
        ) : null}
        {view === "map" ? <MapView data={data} onSelect={(key) => { setActiveKey(key); setView("guide"); }} /> : null}
        {view === "charts" ? <ChartView data={data} activeDesk={activeDesk} onSelect={(key) => { setActiveKey(key); setView("guide"); }} /> : null}
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
