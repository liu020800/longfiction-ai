/* === Helpers & Serializers === */
const $ = (id) => document.getElementById(id);
const qs = (sel, root = document) => root.querySelector(sel);
const qsa = (sel, root = document) => [...root.querySelectorAll(sel)];

function escapeHtml(v) { return String(v ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

function toast(msg, type = "") { ToastSystem.show(msg, type || "info"); }

function showDialog(html) { DialogSystem.show(html); }
function hideDialog() { DialogSystem.hide(); }

function readableSettingText(value) {
  if (value == null) return "";
  if (typeof value === "string") {
    const text = value.trim();
    if ((text.startsWith("{") && text.endsWith("}")) || (text.startsWith("[") && text.endsWith("]"))) {
      try { return readableSettingText(JSON.parse(text)); } catch { return value; }
    }
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item, i) => `${i + 1}. ${readableSettingText(item)}`).filter(Boolean).join("\n");
  }
  if (typeof value === "object") {
    const lines = [];
    const name = value.name || value.title;
    const description = value.description || value.desc || value.summary;
    if (name) lines.push(`体系名称：${name}`);
    if (description) lines.push(String(description));
    const levels = value.levels || value.ranks || value.stages;
    if (Array.isArray(levels) && levels.length) {
      lines.push("等级划分：");
      levels.forEach((item, index) => {
        if (item && typeof item === "object") {
          const rank = item.rank || index + 1;
          const levelName = item.name || item.title || `第${rank}级`;
          const levelDesc = item.description || item.desc || "";
          lines.push(`${rank}. ${levelName}：${levelDesc}`);
        } else {
          lines.push(`${index + 1}. ${item}`);
        }
      });
    }
    const labels = { principle: "运行原理", cost: "代价", limit: "限制", limits: "限制", source: "来源", features: "特征", abilities: "能力", type: "类型", name: "名称", description: "描述", desc: "描述", summary: "概要", rank: "等级", stage: "阶段", power: "实力", level: "等级", element: "属性", faction: "势力", location: "地点", effect: "效果", requirement: "需求", condition: "条件", duration: "持续", cooldown: "冷却", side_effect: "副作用", bonus: "加成", penalty: "惩罚", tags: "标签" };
    Object.entries(value).forEach(([key, item]) => {
      if (["name", "title", "description", "desc", "summary", "levels", "ranks", "stages"].includes(key)) return;
      lines.push(`${labels[key] || key}：${readableSettingText(item)}`);
    });
    return lines.filter(Boolean).join("\n");
  }
  return String(value);
}

function worldToText(world) {
  if (!world) return "";
  const lines = [];
  lines.push(`【力量体系】\n${readableSettingText(world.cultivation_system)}`);
  lines.push(`【世界规则】\n${(world.rules || []).map((r, i) => `${i + 1}. ${r}`).join("\n")}`);
  lines.push(`【势力】\n${(world.factions || []).map((f, i) => `${i + 1}. 名称：${f.name || ""}；类型：${f.type || ""}；描述：${f.description || ""}`).join("\n")}`);
  lines.push(`【历史】\n${(world.history || []).map((r, i) => `${i + 1}. ${r}`).join("\n")}`);
  lines.push(`【地点】\n${(world.locations || []).map((l, i) => `${i + 1}. 名称：${l.name || ""}；描述：${l.description || ""}`).join("\n")}`);
  return lines.filter(Boolean).join("\n\n");
}

function textToWorld(text) {
  const getSection = (name) => {
    const m = text.match(new RegExp(`【${name}】([\\s\\S]*?)(?=\\n\\n【|$)`));
    return m ? m[1].trim() : "";
  };
  const rules = getSection("世界规则").split(/\n+/).map(s => s.replace(/^\d+\.\s*/, '').trim()).filter(Boolean);
  const history = getSection("历史").split(/\n+/).map(s => s.replace(/^\d+\.\s*/, '').trim()).filter(Boolean);
  const factions = getSection("势力").split(/\n+/).map(line => {
    const m = line.match(/名称：([^；]+)；类型：([^；]+)；描述：(.+)/);
    return m ? { name: m[1].trim(), type: m[2].trim(), description: m[3].trim() } : null;
  }).filter(Boolean);
  const locations = getSection("地点").split(/\n+/).map(line => {
    const m = line.match(/名称：([^；]+)；描述：(.+)/);
    return m ? { name: m[1].trim(), description: m[2].trim() } : null;
  }).filter(Boolean);
  return { cultivation_system: readableSettingText(getSection("力量体系")), rules, factions, history, locations };
}

function _statusToText(status) {
  if (!status || typeof status !== 'object') return '';
  const labels = { level: '等级', power: '实力', last_seen_chapter: '最近出场章节', faction: '所属势力', title: '称号', race: '种族', age: '年龄', gender: '性别', occupation: '职业', alignment: '阵营', tier: '段位', rank: '排名', hp: '生命值', mp: '法力值', energy: '能量', mood: '情绪', location: '当前位置', relationship: '关系状态', progress: '进度', goal: '当前目标' };
  return Object.entries(status).filter(([k, v]) => v != null && v !== '').map(([k, v]) => `${labels[k] || k}：${typeof v === 'object' ? JSON.stringify(v) : v}`).join('，');
}

function charactersToText(chars) {
  return (chars || []).map((c, i) => [
    `【角色${i + 1}】`,
    `姓名：${c.name || ""}`,
    `目标：${c.goal || ""}`,
    `性格：${(c.personality || []).join('、')}`,
    `外貌：${c.appearance || ""}`,
    `能力：${(c.abilities || []).join('、')}`,
    `状态：${_statusToText(c.status)}`,
    `说话风格：${readableSettingText(c.voice || {})}`,
  ].join('\n')).join('\n\n');
}

function textToCharacters(text) {
  return text.split(/\n\n(?=【角色\d+】)/).map(block => {
    const pick = (label) => {
      const m = block.match(new RegExp(`${label}：(.+)`));
      return m ? m[1].trim() : "";
    };
    let status = {};
    try { status = JSON.parse(pick("状态") || "{}"); } catch {}
    let voice = {};
    const voiceText = pick("说话风格");
    if (voiceText) {
      voice = { style_hint: voiceText };
    }
    return {
      name: pick("姓名"),
      goal: pick("目标"),
      personality: pick("性格").split(/[、,，]/).map(s => s.trim()).filter(Boolean),
      appearance: pick("外貌"),
      abilities: pick("能力").split(/[、,，]/).map(s => s.trim()).filter(Boolean),
      relationships: [], memory: [], status, voice,
    };
  }).filter(c => c.name);
}

function chaptersToText(chapters) {
  return (chapters || []).map((c, i) => [
    `【第${i + 1}章】`,
    `标题：${c.title || ""}`,
    `目标：${c.goal || ""}`,
    `冲突：${c.conflict || ""}`,
    `场景数：${(c.scenes || []).length}`,
  ].join('\n')).join('\n\n');
}

function textToChapters(text) {
  return text.split(/\n\n(?=【第\d+章】)/).map(block => {
    const pick = (label) => {
      const m = block.match(new RegExp(`${label}：(.+)`));
      return m ? m[1].trim() : "";
    };
    return { title: pick("标题"), goal: pick("目标"), conflict: pick("冲突"), scenes: [] };
  }).filter(c => c.title || c.goal || c.conflict);
}
