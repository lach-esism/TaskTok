/* 示例数据。接入后端后，这个文件整体由 API 响应替换。
   任务字段还没定稿，下面是当前原型用到的全部字段：
   id, title, poster, avatar, cover, cat, level, levelText,
   budget(展示串), budgetNum, deadline(展示串), hours, match, applicants, rate,
   publishedAt, verify, desc, outputs[], accept[], why[], contract[[k,v]], checks[] */

const TASKS = [
  {
    id:'t1', title:'东南亚储能市场：三国进入机会判断', poster:'星辰资本', avatar:'星',
    cover:'assets/cover-market-900.jpg', cat:'市场研究', level:'L3', levelText:'复杂分析',
    budget:'¥5,300', budgetNum:5300, deadline:'72 小时', hours:72, match:96, applicants:17, rate:82,
    publishedAt:isoDaysAgo(0,8), verify:'manual',
    desc:'越南、泰国、马来西亚三国，市场规模、政策窗口与 Top 30 潜在客户，给出进入优先顺序。',
    outputs:['18—20 页决策报告（PDF）','三国政策与装机数据库（Excel）','Top 30 潜在客户清单与决策链','数据来源清单，逐条可溯源'],
    accept:['报告结论需有数据支撑，每个判断注明依据','发包方 48 小时内给出验收结论','任一条数据无法溯源即视为未完成'],
    why:['B2B 研究类任务完成 14 次，评分处于前 8%','英文资料处理能力已被 23 次交付验证','按时率 96%，争议率 0.7%'],
    contract:[['目标','判断三国是否值得进入，并给出优先顺序'],['输入','公开市场数据、政策文件、访谈额度 5 人次'],['交付物','报告 + 数据库 + 线索清单'],['验收标准','发包方逐项核对'],['风险说明','中 · 数据须可溯源']],
    checks:['市场规模与增速（三国）','政策与补贴窗口梳理','Top 30 潜在客户清单','5 位当地客户访谈','竞争格局与替代方案','进入建议与风险提示']
  },
  {
    id:'t2', title:'美国 AI 医疗：近 100 家融资公司地图', poster:'拓元创投', avatar:'拓',
    cover:'assets/cover-bio-900.jpg', cat:'市场研究', level:'L3', levelText:'复杂分析',
    budget:'¥2,400', budgetNum:2400, deadline:'24 小时', hours:24, match:94, applicants:9, rate:79,
    publishedAt:isoDaysAgo(1,14), verify:'metrics',
    desc:'近 12 个月完成融资的 AI 医疗公司，按赛道、轮次与投资人聚类，附可投资标的初筛。',
    outputs:['100 家公司结构化表格（含轮次、金额、领投）','按赛道聚类的分布图','10 家优先跟进标的与理由'],
    accept:['公司数量与融资信息抽检 20 条','每条需附公开来源链接','赛道分类需与约定口径一致'],
    why:['AI 医疗类任务完成 6 次，平均质量分 89','对美股生物科技板块有持续跟踪','结构化管理 100 条以上数据经验'],
    contract:[['目标','形成可跟进的投资标的池'],['输入','公开融资数据库、公司官网、新闻稿'],['交付物','结构化表格 + 分布图 + 初筛'],['验收标准','抽检 20 条 + 口径校验'],['风险说明','中 · 融资信息时效性']],
    checks:['融资事件抓取（近 12 个月）','公司字段补全与去重','赛道聚类与口径统一','优先标的初筛']
  },
  {
    id:'t3', title:'德国工业机器人市场地图', poster:'汉森智造', avatar:'汉',
    cover:'assets/cover-robot-900.jpg', cat:'市场研究', level:'L2', levelText:'专业任务',
    budget:'¥1,800', budgetNum:1800, deadline:'36 小时', hours:36, match:92, applicants:12, rate:85,
    publishedAt:isoDaysAgo(3,11), verify:'manual',
    desc:'德国工业机器人产业链上下游地图，含系统集成商与汽车行业渗透率，用于渠道拓展决策。',
    outputs:['产业链地图（一页）','40 家系统集成商清单','汽车行业渗透率与采购周期说明'],
    accept:['清单企业需可在官网验证','地图层级与调研口径一致'],
    why:['德语资料处理能力已验证 3 次','制造业研究任务完成 5 次','客户复购率 73%，同类客户曾复购 2 次'],
    contract:[['目标','形成可触达的渠道清单'],['输入','行业协会数据、企业官网、招投标信息'],['交付物','地图 + 清单 + 渗透率说明'],['验收标准','企业可验证 + 口径一致'],['风险说明','低 · 公开信息为主']],
    checks:['产业链层级梳理','40 家集成商核对','汽车行业渗透率','采购周期与决策链']
  },
  {
    id:'t4', title:'某 SaaS 销售漏斗诊断：3 个环节在漏水', poster:'云迹科技', avatar:'云',
    cover:'assets/cover-funnel-900.jpg', cat:'数据分析', level:'L2', levelText:'专业任务',
    budget:'¥900', budgetNum:900, deadline:'16 小时', hours:16, match:89, applicants:6, rate:88,
    publishedAt:isoDaysAgo(5,9), verify:'metrics',
    desc:'给一份 6 个月的销售漏斗数据，找出转化损耗最大的三个环节，并给出可执行修正动作。',
    outputs:['漏斗各阶段转化率测算表','损耗归因分析（3 个环节）','修正动作与预期提升区间'],
    accept:['所有转化率须由原始数据算出','归因不得使用相关性替代因果'],
    why:['数据分析类任务完成 21 次','SQL 能力 43 分，但本次以表格计算为主','同类任务平均 9 小时完成'],
    contract:[['目标','找出损耗最大的三个环节'],['输入','6 个月漏斗原始数据'],['交付物','测算表 + 归因 + 动作'],['验收标准','可复算 + 口径说明'],['风险说明','低 · 数据脱敏']],
    checks:['数据清洗与口径确认','各阶段转化率测算','损耗归因','修正动作与预期']
  },
  {
    id:'t5', title:'TikTok 美国区投放：CAC 从 42 降到 35 以下', poster:'澄海出海', avatar:'澄',
    cover:null, cat:'增长投放', level:'L4', levelText:'跨任务协调',
    budget:'¥8,000', budgetNum:8000, deadline:'至 3 月 28 日', hours:0, match:87, applicants:23, rate:74,
    publishedAt:isoDaysAgo(7,16), verify:'manual',
    desc:'诊断素材疲劳与人群重叠，提交 A/B 测试方案并跑到 CAC 达标，附可复用投放 SOP。',
    outputs:['CAC 构成与损耗点清单','两组 A/B 测试方案与预算分配','达标验证数据','可复用投放 SOP'],
    accept:['以投放后台数据为准，CAC 连续 7 天低于 35 美元','测试方案需发包方确认后执行'],
    why:['增长类任务完成 4 次','跨任务协调能力评级 L4','曾有出海客户复购'],
    contract:[['目标','CAC 连续 7 天低于 35 美元'],['输入','近 90 天投放报表、素材库、后台权限'],['交付物','诊断 + 方案 + 验证 + SOP'],['验收标准','后台数据指标验收'],['风险说明','高 · 预算消耗']],
    checks:['投放数据拆解','素材疲劳诊断','A/B 方案提交','达标验证','SOP 沉淀']
  },
  {
    id:'t6', title:'竞品定价情报周报：每周一固定交付', poster:'锐思咨询', avatar:'锐',
    cover:null, cat:'竞品情报', level:'L1', levelText:'简单执行',
    budget:'¥1,200', budgetNum:1200, deadline:'12 小时', hours:12, match:84, applicants:31, rate:91,
    publishedAt:isoDaysAgo(12,8), verify:'manual',
    desc:'跟踪 8 家竞品的定价页与套餐变化，输出结构化周报，异常变动单独标注。',
    outputs:['8 家竞品定价结构化表','变动对比与异常标注','变更截图存档'],
    accept:['字段齐全，变动需附截图','每周一 10:00 前提交'],
    why:['同类情报任务连续交付 11 周','结构化整理能力稳定','适合作为长期订阅型任务'],
    contract:[['目标','持续跟踪竞品定价变动'],['输入','竞品定价页、套餐文档'],['交付物','结构化表 + 变动说明'],['验收标准','字段齐全 + 按时'],['风险说明','低 · 公开页面']],
    checks:['8 家定价页抓取','字段比对','异常变动标注','周报归档']
  }
];

const CATS = ['全部','市场研究','线索挖掘','数据分析','增长投放','竞品情报'];

// 验收方式：发包方怎么判断交付是否合格。desc 写进任务说明；hint 是发布表单里的选项说明。
const VERIFY_METHODS = {
  'manual':{label:'逐项核对', desc:'发包方按验收标准逐条核对交付物。', hint:'你按验收标准一条条核对，适合研究、设计和咨询类成果。'},
  'metrics':{label:'数据指标', desc:'以约定的后台数据或业务指标是否达标为准。', hint:'以约定指标是否达标为准，适合投放、增长和经营类任务。'}
};
const LEVEL_TEXT = {L1:'简单执行',L2:'专业任务',L3:'复杂分析',L4:'跨任务协调'};

/* 任务流程（一端两用：同一身份既接单也发布）
   接单方 workItem.status：
     accepted   已认领，等发包方选人
     active     被选中，执行中（可勾选子任务记录进度）
     submitted  已提交成果，等发包方验收（不能再改）
     rework     发包方要求返工，附原因，改完重新提交
     completed  验收通过，已结算
     declined   发包方选了别人
   发包方 published.status：
     recruiting 招募中，可修改，可从认领者里选定执行者
     working    执行者在做
     reviewing  执行者已提交，等你验收
     done       你已验收通过并结算 */

// 首次打开（本地没有存档）时的接单侧示例状态
const SEED = {
  saved:['t2','t3'],
  recent:['t1','t4','t3'],
  workItems:[
    {taskId:'t2',status:'accepted',addedAt:isoDaysAgo(0,9)},
    {taskId:'t1',status:'active',addedAt:isoDaysAgo(2,11)},
    {taskId:'t4',status:'rework',addedAt:isoDaysAgo(4,16),
      submission:{files:['漏斗测算表.xlsx','诊断报告.pdf'],note:'三个环节的损耗已算出。',at:isoDaysAgo(1,10)},
      review:{decision:'rework',reason:'第二个环节的转化率和原始数据对不上，请按原始表重算并注明口径。',at:isoDaysAgo(0,15)}},
    {taskId:'t6',status:'submitted',addedAt:isoDaysAgo(6,10),
      submission:{files:['竞品定价周报-W46.xlsx'],note:'本周 3 家竞品调价，已附截图。',at:isoDaysAgo(0,11)}},
    {taskId:'t3',status:'completed',addedAt:isoDaysAgo(9,10),completedAt:isoDaysAgo(2,18),score:94,
      submission:{files:['德国工业机器人市场地图.pdf','渠道清单.xlsx'],note:'',at:isoDaysAgo(3,17)},
      review:{decision:'pass',passed:[0,1],at:isoDaysAgo(2,18)}}
  ],
  checks:{t1:[0,1],t4:[0,1,2],t3:[0,1,2,3],t6:[0,1,2]}
};

// 认领者示例：发布任务后，按任务 id 生成稳定的一组认领者
const APPLICANT_POOL = [
  {id:'u1', name:'周宁', avatar:'周', level:'L3', done:42, onTime:97, note:'做过 6 个同类投放诊断，可以从漏斗数据先切入。'},
  {id:'u2', name:'陈墨', avatar:'陈', level:'L2', done:18, onTime:94, note:'熟悉 TikTok 广告后台，三天内可给出第一版方案。'},
  {id:'u3', name:'林夏', avatar:'林', level:'L3', done:65, onTime:91, note:'擅长素材分析，之前把一个客户的 CAC 降了 22%。'},
  {id:'u4', name:'许然', avatar:'许', level:'L4', done:120, onTime:98, note:'可以全程负责，并整理成可复用的投放 SOP。'}
];

// 示例：别人发来的成果（演示发包方验收），按执行者 id 取
const DEMO_SUBMISSION = {files:['投放诊断报告.pdf','A/B 方案.xlsx','复盘与 SOP.docx'], note:'CAC 已连续 7 天低于 35 美元，后台截图在报告第 3 页。'};

// 当前登录用户（一端两用：同一身份既接单也发布）
const CURRENT_USER = {name:'李洋', avatar:'李'};

// 个人中心收入柱状图（演示）
const INCOME_SERIES = [4200,3800,5600,2100,6400,4900,3400,5200,6100,2800,7300,5600,4200];


