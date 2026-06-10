const GUIDE_DATA = {
  roles: [
    {
      key: "beginner",
      label: "第一次使用",
      promise: "按顺序完成路径、缓存、下载、研究，不需要先懂所有参数。",
      route: ["settings", "cache", "download", "research", "tasks"]
    },
    {
      key: "ops",
      label: "数据维护",
      promise: "重点看缓存完整度、下载计划、后台任务与错误定位。",
      route: ["dashboard", "cache", "download", "tasks", "settings"]
    },
    {
      key: "researcher",
      label: "投研分析",
      promise: "先确认数据可用，再进入相似度、ETF、市场风险偏好与 AI 解读。",
      route: ["dashboard", "research", "ai", "tasks"]
    }
  ],
  starterSteps: [
    { title: "配置路径", desk: "系统设置", text: "设置 TDX 路径、数据根目录、复权和运行参数。" },
    { title: "扫描缓存", desk: "缓存资产", text: "确认本地 parquet 与 SQLite catalog 是否能对齐。" },
    { title: "预览计划", desk: "下载任务", text: "选代码、周期、日期窗，先看缺口再执行。" },
    { title: "执行补齐", desk: "执行记录", text: "看任务状态、错误、写入结果，不靠盲猜。" },
    { title: "研究分析", desk: "研究工具", text: "按问题选择历史相似、横截面、ETF 或风偏。" },
    { title: "AI 总结", desk: "AI 工作台", text: "把本地证据交给模型生成可复核的解释。" }
  ],
  lifecycle: [
    { step: "设路径", area: "系统设置", result: "TDX 与 data 根目录可用" },
    { step: "建索引", area: "缓存资产", result: "缓存资产、覆盖率、最近日期" },
    { step: "算缺口", area: "下载任务", result: "计划表、缺失 K 数、覆盖率" },
    { step: "落数据", area: "执行记录", result: "任务状态、错误、写入文件" },
    { step: "出研究", area: "研究工具", result: "相似窗口、ETF、风偏、复盘" },
    { step: "写结论", area: "AI 工作台", result: "基于证据的解释与卡片" }
  ],
  workbenches: [
    {
      key: "dashboard",
      code: "OV",
      title: "总览",
      subtitle: "先判断系统是否健康",
      beginner: "打开后先看这里：路径、缓存、最近任务是否正常，一眼判断今天能不能继续做研究。",
      when: "你不知道数据是否准备好，或者刚启动服务时。",
      inputs: ["本地设置", "缓存索引", "最近任务"],
      actions: ["刷新状态", "跳转下载", "查看缓存资产"],
      outputs: ["缓存概览", "最近任务", "缺口提示"],
      risk: "总览只告诉你状态，不负责修复；发现问题后去对应工作台处理。",
      value: 65,
      complexity: 20,
      coverage: [3, 1, 1, 0, 0, 2],
      checklist: [
        "看 TDX 路径与 data 根目录是否显示正常。",
        "看缓存资产数量、不可用数量、最近任务状态。",
        "如果数据过旧，进入下载任务或缓存资产继续排查。"
      ],
      chart: [
        { label: "环境", value: 86 },
        { label: "缓存", value: 74 },
        { label: "任务", value: 58 },
        { label: "研究", value: 42 }
      ]
    },
    {
      key: "download",
      code: "DL",
      title: "下载任务",
      subtitle: "把缺口变成可执行计划",
      beginner: "这里不是直接乱下数据，而是先生成计划：哪些代码、哪个周期、缺多少 K 线、为什么要更新。",
      when: "需要补齐 1d、5m 等周期数据，或想确认选定日期范围是否真的缺数据。",
      inputs: ["代码池", "周期", "开始/结束日期", "复权方式"],
      actions: ["预览计划", "启动下载", "查看后台任务"],
      outputs: ["下载计划", "缺失 K 数", "覆盖率", "任务 ID"],
      risk: "日期快捷里的 N 天按交易日理解；已有数据也要比较任务交易日与本地交易日偏差。",
      value: 80,
      complexity: 54,
      coverage: [2, 3, 3, 0, 0, 3],
      checklist: [
        "先选周期，确认 5m/1d 不要混淆。",
        "用预览计划看缺口，不要直接执行大批量任务。",
        "计划合理后启动下载，再去执行记录看进度。"
      ],
      chart: [
        { label: "选代码", value: 75 },
        { label: "选周期", value: 92 },
        { label: "算缺口", value: 88 },
        { label: "执行", value: 70 }
      ]
    },
    {
      key: "cache",
      code: "CA",
      title: "缓存资产",
      subtitle: "看本地数据到底有什么",
      beginner: "这是数据库存视图：不是研究结论，而是告诉你哪些股票、指数、ETF 已有缓存，最近日期到哪天。",
      when: "指数列表为空、TDX 路径不对、研究结果异常或下载计划缺口不可信时。",
      inputs: ["data 目录", "SQLite catalog", "parquet 文件"],
      actions: ["扫描缓存", "筛选周期", "查看资产覆盖"],
      outputs: ["资产表", "周期覆盖", "最近 K 线日期"],
      risk: "路径错时，表面上服务能启动，但研究宇宙和指数列表会空。",
      value: 72,
      complexity: 44,
      coverage: [1, 3, 1, 1, 0, 2],
      checklist: [
        "扫描缓存并确认数据根目录。",
        "按周期过滤，查看 1d/5m 是否都有记录。",
        "如果指数或 ETF 缺失，回到设置校准 TDX 路径。"
      ],
      chart: [
        { label: "股票", value: 96 },
        { label: "指数", value: 68 },
        { label: "ETF", value: 80 },
        { label: "分钟线", value: 52 }
      ]
    },
    {
      key: "research",
      code: "RS",
      title: "研究工具",
      subtitle: "把本地行情转成投研问题",
      beginner: "研究工具不是一个按钮，而是一组问题模板：找相似走势、横截面对比、多股复盘、ETF 跟踪、市场风偏。",
      when: "数据已经准备好，想回答“现在像哪段历史、哪些资产更强、市场是否收缩”。",
      inputs: ["本地 K 线", "研究参数", "股票/ETF/指数代码"],
      actions: ["运行研究", "保存快照", "导出 JSON", "载入多股复盘"],
      outputs: ["匹配结果", "K 线窗口", "排序表", "RAI 与热力图"],
      risk: "研究结论依赖本地数据完整度；先确认缓存，再解释结果。",
      value: 94,
      complexity: 76,
      coverage: [0, 1, 0, 3, 2, 1],
      checklist: [
        "先选一个明确问题，不要同时改很多高级参数。",
        "历史相似看时间窗口，横截面看同期候选。",
        "市场风偏先读 RAI，再读风险释放路径和日报。"
      ],
      chart: [
        { label: "历史相似", value: 80 },
        { label: "横截面", value: 76 },
        { label: "ETF", value: 72 },
        { label: "市场风偏", value: 92 }
      ],
      subtools: [
        { name: "历史相似", use: "找某只标的过去相似窗口，适合复盘走势结构。" },
        { name: "横截面相似", use: "在同一时间段内找走势相似资产，适合候选筛选。" },
        { name: "多股复盘", use: "把多个标的放在一个窗口里排序、对比、生成复盘材料。" },
        { name: "场内ETF跟踪", use: "按类别看全量 ETF 行情、收益率、规模与缓存状态。" },
        { name: "市场风险偏好", use: "用 RAI、风险释放热力图、资金回流候选判断市场阶段。" }
      ]
    },
    {
      key: "ai",
      code: "AI",
      title: "AI 工作台",
      subtitle: "让模型解释本地证据",
      beginner: "AI 工作台不会凭空查行情，它读取本地证据和你的提示词，生成可追溯的解释、卡片和批注。",
      when: "你已经有研究结果，想把结果转成自然语言、复盘脚本或逐股锐评。",
      inputs: ["本地证据", "提示词", "模型配置"],
      actions: ["解析命令", "生成解读", "检查证据引用"],
      outputs: ["解释文本", "脚本卡片", "证据引用", "风险提示"],
      risk: "未配置模型时只能走本地规则；涉及结论必须能回到证据字段。",
      value: 82,
      complexity: 63,
      coverage: [0, 0, 0, 1, 3, 1],
      checklist: [
        "先在系统设置里填模型 URL、Key 和模型名。",
        "从研究结果进入 AI，不要只给空泛问题。",
        "看 evidence refs，确认结论能追溯。"
      ],
      chart: [
        { label: "命令解析", value: 70 },
        { label: "复盘生成", value: 86 },
        { label: "证据引用", value: 78 },
        { label: "人工复核", value: 62 }
      ]
    },
    {
      key: "tasks",
      code: "TK",
      title: "执行记录",
      subtitle: "所有后台任务的黑匣子",
      beginner: "如果按钮变灰、下载卡住、Parallels 报错，都先来这里看任务状态和错误，而不是反复点击。",
      when: "任何后台动作启动后：下载、扫描、研究、AI，都需要确认是否完成或失败。",
      inputs: ["任务 ID", "后台状态", "写入结果"],
      actions: ["刷新任务", "查看错误", "定位写入结果"],
      outputs: ["状态表", "事件记录", "质量门禁", "错误详情"],
      risk: "错误要显式暴露，不能用静默 fallback 掩盖。",
      value: 76,
      complexity: 38,
      coverage: [1, 1, 2, 1, 0, 3],
      checklist: [
        "任务启动后看状态，不要只等按钮恢复。",
        "失败时复制错误摘要，判断是路径、Parallels 还是数据问题。",
        "看写入结果确认实际落盘。"
      ],
      chart: [
        { label: "排队", value: 20 },
        { label: "运行", value: 45 },
        { label: "写入", value: 72 },
        { label: "完成", value: 100 }
      ]
    },
    {
      key: "settings",
      code: "ST",
      title: "系统设置",
      subtitle: "先把边界条件设对",
      beginner: "这里决定所有模块是否能读到正确数据：TDX 路径、data 根目录、默认周期、AI 参数都在这里。",
      when: "第一次使用、换机器、换通达信目录、指数/ETF 列表为空、AI 不可用时。",
      inputs: ["TDX 路径", "data 根目录", "AI API", "默认参数"],
      actions: ["选择目录", "保存配置", "测试路径"],
      outputs: ["可复用设置", "运行环境", "AI 配置"],
      risk: "路径看似只影响设置页，实际会影响下载、缓存、研究、ETF 和指数读取。",
      value: 70,
      complexity: 46,
      coverage: [3, 1, 1, 1, 1, 2],
      checklist: [
        "先保存 TDX 路径和 data 根目录。",
        "确认复权、默认周期和批量参数。",
        "需要 AI 时再配置接口，不要写进源码。"
      ],
      chart: [
        { label: "TDX路径", value: 90 },
        { label: "数据根", value: 88 },
        { label: "默认参数", value: 60 },
        { label: "AI配置", value: 55 }
      ]
    }
  ],
  matrixColumns: ["准备", "采集", "校验", "研究", "解释", "追踪"]
};

Object.assign(window, { GUIDE_DATA });
