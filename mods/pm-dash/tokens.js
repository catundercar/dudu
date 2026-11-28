// Board Token Analytics UI: header pulse pill + collapsible bottom analytics shelf (`board-flat-fill-style`).
import { div, svg } from 'gpui-kit';
import { v_flex, h_flex, Popup } from 'gpui-base';
import {
  word, withAlpha, solidText, formatTokens, formatUsd, formatPct, formatCompactInt,
  selectTokenScope, filterTokenSlice, selectBreakdownRows, sparklineBars,
  TOKEN_RANGES, TOKEN_METRICS, TOKEN_DIMS, TOKEN_AGENTS, RUNTIME_ORDER,
} from './model.js';
import { openProject } from './projects.js';

const ICON = name => `mods/pm-dash/${name}.svg`;

function agentColor(agent, t) {
  if (agent === 'claude') return t.ansi4 ?? t.accent;
  if (agent === 'fable') return t.ansi5 ?? t.accent;
  if (agent === 'agy') return t.ansi6 ?? t.ansi2;
  if (agent === 'codex') return t.ansi3 ?? t.accent;
  if (agent === 'pi') return t.ansi2 ?? t.accent;
  return t.muted;
}

function resolveTodaySummary(v) {
  const scoped = selectTokenScope(v.tokenData, v.scope, v.allState?.pms || v.state?.pms);
  const todaySlice = scoped?.ranges?.today || null;
  const filtered = filterTokenSlice(todaySlice, { agent: v.tokensAgent || 'all', metric: 'tokens', dim: 'task' });
  return { scoped, todaySlice, filtered };
}

function pillBar(id, options, active, onPick, t, { compact = false } = {}) {
  return h_flex().id(id).flex_none().p(3).gap(2).rounded(9).bg(t.surface)
    .children(options.map(([key, label, dotColor]) => {
      const isOn = key === active;
      return h_flex().id(`${id}-${key}`).h(compact ? 24 : 26).px(compact ? 8 : 10).gap(5).rounded(7)
        .items_center().cursor_pointer().text_size(compact ? 11.5 : 12)
        .when(isOn, el => el.bg(t.raised).text_color(t.foreground).font_semibold())
        .when(!isOn, el => el.text_color(t.muted).hover(s => s.text_color(t.foreground)))
        .on_click((_e, cx) => { cx.stop_propagation(); onPick(key, cx); })
        .when(Boolean(dotColor), el => el.child(div().size(6).rounded(3).flex_none().bg(dotColor)))
        .child(label);
    }));
}

function subSwitcher(id, options, active, onPick, t) {
  return h_flex().id(id).flex_none().p(2).gap(2).rounded(8).bg(t.canvas)
    .children(options.map(([key, label]) => {
      const isOn = key === active;
      return h_flex().id(`${id}-${key}`).h(22).px(9).rounded(6).items_center().cursor_pointer().text_size(11.5)
        .when(isOn, el => el.bg(t.raised).text_color(t.foreground).font_semibold())
        .when(!isOn, el => el.text_color(t.muted).hover(s => s.text_color(t.foreground)))
        .on_click((_e, cx) => { cx.stop_propagation(); onPick(key, cx); })
        .child(label);
    }));
}

function segBar(segments, total, t, { height = 4 } = {}) {
  const track = h_flex().w_full().h(height).rounded(height / 2).bg(t.raised).overflow_hidden().gap(1);
  if (!(total > 0)) return track;
  for (const [color, val] of segments) {
    if (!(val > 0)) continue;
    const pct = Math.max(1.5, (val / total) * 100);
    track.child(div().h_full().flex_basis(0).flex_grow(pct).bg(color));
  }
  return track;
}

export function renderTokenPulsePill(v, t, small = false) {
  const lang = v.state?.lang;
  const { scoped, filtered } = resolveTodaySummary(v);
  const kpi = filtered.kpi;
  const hasData = Boolean(scoped?.ranges);
  const wideEnough = !small && (v.size?.width || 980) >= 1040;

  return h_flex().id('token-pulse-pill').h(52).px(small ? 10 : 14).gap(small ? 8 : 11)
    .flex_none().rounded(12).bg(t.surface).items_center().cursor_pointer()
    .hover(s => s.bg(t.raised))
    .accessibility_label(word(lang, v.tokensExpanded ? 'tokCollapseTip' : 'tokExpandTip'))
    .on_click((_e, cx) => { cx.stop_propagation(); v.toggleTokens(cx); })
    .child(div().size(7).rounded(3.5).flex_none().bg(hasData ? (t.ansi6 ?? t.ansi2) : t.dim))
    .child(h_flex().gap(5).items_baseline()
      .child(div().text_size(small ? 14 : 15).font_bold().text_color(hasData ? t.foreground : t.dim)
        .child(hasData ? formatTokens(kpi.total_tokens) : '--'))
      .child(div().text_size(11.5).text_color(t.muted).child(word(lang, 'tokToday'))))
    .when(hasData, el => el
      .child(div().w(1).h(18).flex_none().bg(t.border))
      .child(div().text_size(small ? 13 : 14).font_semibold().text_color(t.foreground).child(formatUsd(kpi.cost_usd)))
      .when(wideEnough, w => w
        .child(div().w(1).h(18).flex_none().bg(t.border))
        .child(div().text_size(12).text_color(t.muted)
          .child(`${formatPct(kpi.cache_hit_rate, 0)} ${word(lang, 'tokHit')}`))));
}

function renderCollapsedBar(v, t, scoped, filtered) {
  const lang = v.state?.lang;
  const kpi = filtered.kpi;
  const hasData = Boolean(scoped?.ranges);
  const bars = sparklineBars(filtered.buckets, 12);

  const spark = h_flex().h(18).gap(2).items_end().flex_none();
  for (const [idx, ratio] of bars.entries()) {
    const hPx = ratio > 0 ? Math.max(3, Math.round(ratio * 18)) : 2;
    const activeColor = idx >= 8 ? (t.ansi6 ?? t.ansi4) : (t.ansi4 ?? t.accent);
    spark.child(div().w(3).h(hPx).rounded(1.5).bg(ratio > 0 ? activeColor : t.raised));
  }

  const pm = filtered.pm || {};
  const summaryParts = hasData
    ? [
        `${word(lang, 'tokToday')} ${formatTokens(kpi.total_tokens)}`,
        ...(pm.total_tokens > 0 ? [word(lang, 'tokPmInline', formatTokens(pm.total_tokens))] : []),
        word(lang, 'tokReqs', formatCompactInt(kpi.requests)),
        `~${formatUsd(kpi.cost_usd)}`,
        `${formatPct(kpi.cache_hit_rate)} ${word(lang, 'tokCacheHit')}`,
      ].join(' · ')
    : (v.tokensLoading ? word(lang, 'tokLoading') : word(lang, 'tokNoData'));

  return h_flex().id('token-shelf-bar').w_full().h(44).px(16).gap(12).flex_none()
    .rounded(12).bg(t.surface).items_center().cursor_pointer()
    .hover(s => s.bg(t.raised))
    .accessibility_label(word(lang, 'tokExpandTip'))
    .on_click((_e, cx) => { cx.stop_propagation(); v.toggleTokens(cx); })
    .child(div().size(7).rounded(3.5).flex_none().bg(hasData ? (t.ansi6 ?? t.ansi2) : t.dim))
    .child(div().flex_none().text_size(13).font_semibold().text_color(t.foreground).child(word(lang, 'tokUsage')))
    .child(div().flex_1().min_w(0).truncate().text_size(12.5).text_color(t.muted).child(summaryParts))
    .child(spark)
    .child(svg(ICON('chevron-down')).size(14).flex_none().text_color(t.muted));
}

function renderKpiCards(v, t, kpi, pm, width) {
  const lang = v.state?.lang;
  const totalInOutCache = kpi.input_tokens + kpi.output_tokens + kpi.cache_read_tokens + kpi.cache_write_tokens;
  const hasPm = (pm?.total_tokens || 0) > 0;
  const costSubText = hasPm
    ? word(lang, 'tokPmCostSub', formatTokens(pm.total_tokens), formatUsd(pm.cost_usd), formatPct(pm.share))
    : word(lang, 'tokKpiCostSub');
  const hitAgentRates = Object.entries(kpi.by_agent_hit_rate || {})
    .map(([a, r]) => `${word(lang, { claude: 'tokAgentClaude', agy: 'tokAgentAgy', codex: 'tokAgentCodex', pi: 'tokAgentPi' }[a] || a)} ${formatPct(r)}`)
    .join(' / ');
  const reqAgentParts = Object.entries(kpi.by_agent_requests || {})
    .map(([a, n]) => `${word(lang, { claude: 'tokAgentClaude', agy: 'tokAgentAgy', codex: 'tokAgentCodex', pi: 'tokAgentPi' }[a] || a)} ${formatCompactInt(n)}`)
    .join(' · ');

  const card1 = v_flex().flex_1().min_w(0).p(14).gap(9).rounded(13).bg(t.surface)
    .child(h_flex().justify_between().items_center().gap(6)
      .child(div().text_size(12).text_color(t.muted).child(word(lang, 'tokKpiTotal')))
      .child(div().text_size(11).text_color(t.dim).child(word(lang, 'tokKpiTotalTag'))))
    .child(div().text_size(24).font_bold().text_color(t.foreground).child(formatTokens(kpi.total_tokens)))
    .child(segBar([
      [t.ansi4 ?? t.accent, kpi.input_tokens],
      [t.ansi6 ?? t.accent, kpi.output_tokens],
      [t.ansi2 ?? t.accent, kpi.cache_read_tokens + kpi.cache_write_tokens],
    ], totalInOutCache, t))
    .child(div().truncate().text_size(11.5).text_color(t.dim).child(word(
      lang,
      'tokKpiTotalSub',
      formatTokens(kpi.input_tokens),
      formatTokens(kpi.output_tokens),
      formatTokens(kpi.cache_read_tokens + kpi.cache_write_tokens),
    )));

  const card2 = v_flex().flex_1().min_w(0).p(14).gap(9).rounded(13).bg(t.surface)
    .child(h_flex().justify_between().items_center().gap(6)
      .child(div().text_size(12).text_color(t.muted).child(word(lang, 'tokKpiReqs')))
      .child(div().px(7).py(2).rounded(7).bg(t.raised).text_size(11).text_color(t.muted)
        .child(word(lang, 'tokTasksSess', kpi.tasks, kpi.sessions))))
    .child(div().text_size(24).font_bold().text_color(t.foreground).child(formatCompactInt(kpi.requests)))
    .child(segBar(
      Object.entries(kpi.by_agent_requests || {}).map(([a, n]) => [agentColor(a, t), n]),
      kpi.requests,
      t,
    ))
    .child(h_flex().justify_between().items_center().gap(6)
      .child(div().flex_1().min_w(0).truncate().text_size(11.5).text_color(t.dim).child(reqAgentParts || '—'))
      .when(kpi.errors > 0, el => el.child(div().flex_none().text_size(11.5).font_medium()
        .text_color(t.blocked).child(word(lang, 'tokKpiErr', kpi.errors)))));

  const card3 = v_flex().flex_1().min_w(0).p(14).gap(9).rounded(13).bg(t.surface)
    .child(h_flex().justify_between().items_center().gap(6)
      .child(div().text_size(12).text_color(t.muted).child(word(lang, 'tokKpiCost')))
      .when(kpi.cache_savings_usd > 0, el => el.child(div().px(7).py(2).rounded(7)
        .bg(withAlpha(t.ansi2, .16)).text_size(11).font_medium().text_color(t.ansi2)
        .child(word(lang, 'tokKpiSaved', formatUsd(kpi.cache_savings_usd))))))
    .child(div().text_size(24).font_bold().text_color(t.foreground).child(formatUsd(kpi.cost_usd)))
    .child(segBar([[t.ansi2, kpi.cost_usd]], Math.max(1, kpi.cost_usd), t))
    .child(div().truncate().text_size(11.5).text_color(t.dim).child(costSubText));

  const card4 = v_flex().flex_1().min_w(0).p(14).gap(9).rounded(13).bg(t.surface)
    .child(h_flex().justify_between().items_center().gap(6)
      .child(div().text_size(12).text_color(t.muted).child(word(lang, 'tokKpiHit')))
      .child(div().text_size(11).text_color(t.dim).child(word(lang, 'tokKpiHitTag'))))
    .child(div().text_size(24).font_bold().text_color(t.foreground).child(formatPct(kpi.cache_hit_rate, 2)))
    .child(segBar([[t.ansi6 ?? t.ansi2, kpi.cache_hit_rate]], 1, t))
    .child(div().truncate().text_size(11.5).text_color(t.dim)
      .child(word(lang, 'tokKpiHitSub', formatTokens(kpi.prompt_tokens), hitAgentRates)));

  if (width >= 820) {
    return h_flex().w_full().gap(10).items_stretch().child(card1).child(card2).child(card3).child(card4);
  }
  return v_flex().w_full().gap(10)
    .child(h_flex().w_full().gap(10).items_stretch().child(card1).child(card2))
    .child(h_flex().w_full().gap(10).items_stretch().child(card3).child(card4));
}

function formatMetricValue(metric, v) {
  if (metric === 'cost') return formatUsd(v);
  if (metric === 'requests') return formatCompactInt(v);
  return formatTokens(v);
}

function renderBarTooltip(v, b, metric, t) {
  const lang = v.state?.lang;
  const fill = [t.raised, t.popover, t.surface].find(c => c && c !== t.canvas) || t.raised;
  const subParts = [];
  for (const a of ['claude', 'agy', 'codex', 'pi']) {
    const val = metric === 'cost' ? b.by_agent_cost?.[a] : metric === 'requests' ? b.by_agent_requests?.[a] : b.by_agent_tokens?.[a];
    if (val > 0) subParts.push(`${word(lang, { claude: 'tokAgentClaude', agy: 'tokAgentAgy', codex: 'tokAgentCodex', pi: 'tokAgentPi' }[a])} ${formatMetricValue(metric, val)}`);
  }
  const isPeak = b.key && b.key === v._peakBarKey;
  return v_flex().w(220).px(11).py(8).gap(4).rounded(9).bg(fill).border_1().border_color(t.border).shadow_lg()
    .child(h_flex().justify_between().items_center().gap(6)
      .child(div().text_size(11.5).font_semibold().text_color(t.foreground)
        .child(isPeak ? `${b.label} · ${word(lang, 'tokPeak')}` : b.label))
      .child(div().text_size(11).text_color(t.dim).child(word(lang, 'tokReqs', formatCompactInt(b.requests)))))
    .child(div().text_size(14).font_bold().text_color(t.foreground)
      .child(`${formatTokens(b.total_tokens)} · ~${formatUsd(b.cost_usd)}`))
    .when(subParts.length > 0, el => el.child(div().text_size(11).text_color(t.muted).child(subParts.join(' · '))));
}

function renderChartCard(v, t, view) {
  const lang = v.state?.lang;
  const metric = v.tokensMetric || 'tokens';
  const subKey = view.bucketMode === 'hour' ? 'tokChartSubHour' : view.bucketMode === 'week' ? 'tokChartSubWeek' : 'tokChartSubDay';
  const chartH = 148;
  const maxVal = view.maxBucket > 0 ? view.maxBucket : 1;
  v._peakBarKey = view.peakBucket?.key || '';

  const yLabels = v_flex().w(44).h(chartH).justify_between().items_end().pr(6).flex_none()
    .child(div().text_size(10.5).text_color(t.dim).child(view.maxBucket > 0 ? formatMetricValue(metric, view.maxBucket) : ''))
    .child(div().text_size(10.5).text_color(t.dim).child(view.maxBucket > 0 ? formatMetricValue(metric, view.maxBucket / 2) : ''))
    .child(div().text_size(10.5).text_color(t.dim).child('0'));

  const barsRow = h_flex().flex_1().min_w(0).h(chartH).items_end().gap(view.buckets.length > 20 ? 3 : 5);
  for (const [idx, b] of view.buckets.entries()) {
    const hovered = v.hoverTokenBar === b.key;
    const totalPx = b.value > 0 ? Math.max(4, Math.round((b.value / maxVal) * (chartH - 6))) : 2;
    const stack = v_flex().w_full().max_w(28).h(totalPx).rounded_t(3).overflow_hidden().justify_end();
    if (b.value <= 0 || !b.segments.length) {
      stack.bg(withAlpha(t.raised, .9));
    } else {
      for (const seg of [...b.segments].reverse()) {
        stack.child(div().w_full().flex_basis(0).flex_grow(Math.max(1, seg.value)).bg(agentColor(seg.key, t)));
      }
    }
    let col = v_flex().id(`tok-bar-${b.key}`).flex_1().min_w(0).h_full().justify_end().items_center()
      .on_hover((over, cx) => {
        if (over) { if (v.hoverTokenBar !== b.key) { v.hoverTokenBar = b.key; cx.notify(); } }
        else if (v.hoverTokenBar === b.key) { v.hoverTokenBar = null; cx.notify(); }
      })
      .child(stack);
    if (hovered && b.value > 0) {
      const rightSide = idx >= view.buckets.length - 4;
      const popAnchor = div().absolute().top(-6).w(0).h(0);
      if (rightSide) popAnchor.right(0);
      else popAnchor.left(0);
      col = col.relative().child(
        popAnchor.child(
          Popup.new(`tok-bar-pop-${b.key}`, div().w(0).h(0))
            .anchor(rightSide ? 'bottom_right' : 'bottom_left')
            .content(renderBarTooltip(v, b, metric, t)),
        ),
      );
    }
    barsRow.child(col);
  }

  let xTicks = [];
  if (view.buckets.length <= 8) {
    xTicks = view.buckets.map(b => b.label);
  } else if (view.bucketMode === 'hour' && view.buckets.length === 24) {
    xTicks = [0, 4, 8, 12, 16, 20, 23].map(i => view.buckets[i]?.label || '');
  } else if (view.buckets.length > 0) {
    const count = 6;
    for (let k = 0; k < count; k++) {
      const idx = Math.round((k * (view.buckets.length - 1)) / (count - 1));
      xTicks.push(view.buckets[idx]?.label || '');
    }
  }
  const xRow = h_flex().w_full().pl(44).pt(6).justify_between().items_center()
    .children(xTicks.map(lbl => div().flex_none().whitespace_nowrap().text_size(10.5).text_color(t.dim).child(lbl)));

  const plot = div().relative().w_full().h(chartH)
    .child(v_flex().absolute().inset_0().pl(44).justify_between()
      .child(div().w_full().h(1).bg(withAlpha(t.border, .45)))
      .child(div().w_full().h(1).bg(withAlpha(t.border, .35)))
      .child(div().w_full().h(1).bg(withAlpha(t.border, .6))))
    .child(h_flex().relative().w_full().h(chartH).items_end().child(yLabels).child(barsRow));

  return v_flex().flex_1().min_w(0).p(16).gap(14).rounded(14).bg(t.surface)
    .child(h_flex().justify_between().items_center().gap(8)
      .child(subSwitcher('tok-metric', TOKEN_METRICS.map(m => [m, word(lang, { tokens: 'tokMetricTokens', cost: 'tokMetricCost', requests: 'tokMetricRequests' }[m])]),
        metric, (m, cx) => { v.tokensMetric = m; cx.notify(); }, t))
      .child(div().truncate().text_size(11.5).text_color(t.dim).child(word(lang, subKey))))
    .when(view.buckets.length > 0, el => el.child(v_flex().w_full().child(plot).child(xRow)))
    .when(!view.buckets.length, el => el.child(div().h(chartH).items_center().justify_center().text_size(12.5).text_color(t.dim).child(word(lang, 'tokNoData'))));
}

function jumpToTask(v, row) {
  if (!row) return;
  const targetPm = row.pm || v.scope || v.allState?.pms?.[0]?.name || v.state?.pms?.[0]?.name || '';
  if (!targetPm) return;
  const threadId = row.id && !row.id.startsWith('pm:') && !row.id.startsWith('other:') ? row.id : '';
  openProject(targetPm, '', threadId);
}

function renderBreakdownCard(v, t, view) {
  const lang = v.state?.lang;
  const dim = v.tokensDim || 'task';
  const subKey = dim === 'model' ? 'tokDimSubModel' : dim === 'agent' ? 'tokDimSubAgent' : 'tokDimSubTask';
  const list = selectBreakdownRows(view.rows, dim, 6);
  const peakVal = Math.max(1, ...list.map(r => (v.tokensMetric === 'cost' ? r.cost_usd : v.tokensMetric === 'requests' ? r.requests : r.total_tokens) || 0));

  const rowsEl = v_flex().w_full().gap(10);
  if (!list.length) {
    rowsEl.child(div().py(24).text_size(12.5).text_color(t.dim).child(word(lang, 'tokNoData')));
  } else if (dim === 'model') {
    for (const m of list) {
      const val = v.tokensMetric === 'cost' ? m.cost_usd : v.tokensMetric === 'requests' ? m.requests : m.total_tokens;
      const color = m.is_advisor ? agentColor('fable', t) : agentColor(m.agent, t);
      const badgeText = m.is_advisor ? `${word(lang, 'tokAgentClaude')} · ${word(lang, 'tokAdvisorBadge')}` : m.agent;
      const cwText = m.cache_write_available ? word(lang, 'tokCacheWriteAmt', formatTokens(m.cache_write_tokens)) : word(lang, 'tokCacheWriteUnavail');
      const subText = [
        word(lang, 'tokReqs', formatCompactInt(m.requests)),
        `${word(lang, 'tokKpiTotalSub', formatTokens(m.input_tokens), formatTokens(m.output_tokens), formatTokens(m.cache_read_tokens))}`,
        cwText,
        ...(m.pm_tokens > 0 ? [word(lang, 'tokPmModelSub', formatTokens(m.pm_tokens))] : []),
        `${formatPct(m.cache_hit_rate)} ${word(lang, 'tokHit')}`,
      ].join(' · ');

      rowsEl.child(v_flex().gap(4)
        .child(h_flex().justify_between().items_center().gap(8)
          .child(h_flex().flex_1().min_w(0).gap(7).items_center()
            .child(div().size(7).rounded(3.5).flex_none().bg(color))
            .child(div().truncate().text_size(12.5).font_semibold().text_color(t.foreground).child(m.model))
            .child(div().flex_none().px(6).py(1).rounded(5).bg(t.raised).text_size(10.5).text_color(t.muted).child(badgeText)))
          .child(div().flex_none().text_size(12.5).font_semibold().text_color(t.foreground)
            .child(`${formatUsd(m.cost_usd)} · ${formatTokens(m.total_tokens)}`)))
        .child(segBar([[color, val]], peakVal, t))
        .child(div().truncate().text_size(11).text_color(t.dim).child(subText)));
    }
  } else if (dim === 'agent') {
    for (const a of list) {
      const val = v.tokensMetric === 'cost' ? a.cost_usd : v.tokensMetric === 'requests' ? a.requests : a.total_tokens;
      const color = agentColor(a.agent, t);
      const active = a.total_tokens > 0 || a.requests > 0;
      const cwText = a.cache_write_available ? word(lang, 'tokCacheWriteAmt', formatTokens(a.cache_write_tokens)) : word(lang, 'tokCacheWriteUnavail');
      const subText = active
        ? [
            word(lang, 'tokReqs', formatCompactInt(a.requests)),
            word(lang, 'tokTasksSess', a.tasks, a.sessions),
            ...(a.pm_tokens > 0 ? [word(lang, 'tokPmAgentSub', formatTokens(a.pm_tokens), formatUsd(a.pm_cost_usd))] : []),
            cwText,
            `${formatPct(a.cache_hit_rate)} ${word(lang, 'tokHit')}`,
          ].join(' · ')
        : `${word(lang, 'tokReqs', 0)} · ${word(lang, 'tokAdapterReady')}`;

      rowsEl.child(v_flex().gap(4).opacity(active ? 1 : .65)
        .child(h_flex().justify_between().items_center().gap(8)
          .child(h_flex().flex_1().min_w(0).gap(7).items_center()
            .child(div().size(7).rounded(3.5).flex_none().bg(active ? color : t.dim))
            .child(div().truncate().text_size(12.5).font_semibold().text_color(t.foreground).child(a.label)))
          .child(div().flex_none().text_size(12.5).font_semibold().text_color(active ? t.foreground : t.dim)
            .child(`${formatTokens(a.total_tokens)} · ${formatUsd(a.cost_usd)}`)))
        .child(segBar([[color, val]], peakVal, t))
        .child(div().truncate().text_size(11).text_color(t.dim).child(subText)));
    }
  } else {
    for (const row of list) {
      const val = v.tokensMetric === 'cost' ? row.cost_usd : v.tokensMetric === 'requests' ? row.requests : row.total_tokens;
      const isPm = row.role === 'pm';
      const primaryColor = isPm ? (t.ansi6 ?? t.accent) : agentColor(row.agents?.[0] || 'claude', t);
      const tag = row.number > 0 ? `#${row.number}` : isPm ? 'PM' : '';
      const hasSplit = !isPm && v.tokensMetric === 'tokens' && row.review_tokens > 0 && row.work_tokens > 0;
      const hasCostSplit = !isPm && v.tokensMetric === 'cost' && row.review_cost_usd > 0 && row.work_cost_usd > 0;
      let barSegs;
      if (isPm && (row.agents?.length || 0) > 1) {
        const srcMap = v.tokensMetric === 'cost' ? row.by_agent_cost : v.tokensMetric === 'requests' ? row.by_agent_requests : row.by_agent;
        barSegs = RUNTIME_ORDER
          .map(a => [agentColor(a, t), Number(srcMap?.[a]) || 0])
          .filter(([, av]) => av > 0);
        if (!barSegs.length) barSegs = [[primaryColor, val]];
      } else if (hasSplit) {
        barSegs = [[primaryColor, row.work_tokens], [agentColor('fable', t), row.review_tokens]];
      } else if (hasCostSplit) {
        barSegs = [[primaryColor, row.work_cost_usd], [agentColor('fable', t), row.review_cost_usd]];
      } else {
        barSegs = [[primaryColor, val]];
      }
      const barTotal = peakVal;
      const subParts = [word(lang, 'tokReqs', formatCompactInt(row.requests))];
      const hasIo = ((row.input_tokens || 0) + (row.output_tokens || 0) + (row.cache_read_tokens || 0) + (row.cache_write_tokens || 0)) > 0;
      if (isPm && hasIo) {
        subParts.push(word(
          lang,
          'tokKpiTotalSub',
          formatTokens(row.input_tokens || 0),
          formatTokens(row.output_tokens || 0),
          formatTokens((row.cache_read_tokens || 0) + (row.cache_write_tokens || 0)),
        ));
      } else if (row.review_tokens > 0) {
        subParts.push(`${word(lang, 'tokCoding')} ${formatTokens(row.work_tokens)} + ${word(lang, 'tokReview')} ${formatTokens(row.review_tokens)}`);
      }
      if (row.models?.length) subParts.push(row.models.slice(0, 2).join(' + '));
      subParts.push(word(lang, 'tokShare', formatPct(row.share)));

      rowsEl.child(v_flex().id(`tok-task-${row.id}`).gap(4).p(4).mx(-4).rounded(7)
        .cursor_pointer().hover(s => s.bg(withAlpha(t.raised, .65)))
        .on_click((_e, cx) => { cx.stop_propagation(); jumpToTask(v, row); })
        .child(h_flex().justify_between().items_center().gap(8)
          .child(h_flex().flex_1().min_w(0).gap(6).items_center()
            .child(div().size(7).rounded(3.5).flex_none().bg(primaryColor))
            .when(Boolean(tag), el => el.child(div().flex_none().px(5).py(1).rounded(5)
              .bg(isPm ? withAlpha(primaryColor, .18) : t.raised)
              .font_family('monospace').text_size(10.5)
              .when(isPm, badge => badge.font_semibold().text_color(primaryColor))
              .when(!isPm, badge => badge.text_color(t.muted))
              .child(tag)))
            .child(div().flex_1().min_w(0).truncate().text_size(12.5).font_semibold().text_color(t.foreground).child(row.title)))
          .child(div().flex_none().text_size(12.5).font_semibold().text_color(t.foreground)
            .child(`${formatTokens(row.total_tokens)} · ${formatUsd(row.cost_usd)}`)))
        .child(segBar(barSegs, barTotal, t))
        .child(div().truncate().text_size(11).text_color(t.dim).child(subParts.join(' · '))));
    }
  }

  return v_flex().flex_1().min_w(0).p(16).gap(12).rounded(14).bg(t.surface)
    .child(h_flex().justify_between().items_center().gap(8)
      .child(subSwitcher('tok-dim', TOKEN_DIMS.map(d => [d, word(lang, { model: 'tokDimModel', task: 'tokDimTask', agent: 'tokDimAgent' }[d])]),
        dim, (d, cx) => { v.tokensDim = d; cx.notify(); }, t))
      .child(div().truncate().text_size(11.5).text_color(t.dim).child(word(lang, subKey))))
    .child(rowsEl);
}

export function renderTokenShelf(v, g, t) {
  const lang = v.state?.lang;
  const scoped = selectTokenScope(v.tokenData, v.scope, v.allState?.pms || v.state?.pms);
  const wrap = div().id('token-shelf').w(g.frame.width).px(g.frame.inset).pb(24).flex_none();

  if (!v.tokensExpanded) {
    const todaySlice = scoped?.ranges?.today || null;
    const filtered = filterTokenSlice(todaySlice, { agent: v.tokensAgent || 'all', metric: 'tokens', dim: 'task' });
    return wrap.child(renderCollapsedBar(v, t, scoped, filtered));
  }

  const range = TOKEN_RANGES.includes(v.tokensRange) ? v.tokensRange : 'today';
  const rawSlice = scoped?.ranges?.[range] || null;
  const view = filterTokenSlice(rawSlice, {
    agent: v.tokensAgent || 'all',
    metric: v.tokensMetric || 'tokens',
    dim: v.tokensDim || 'task',
  });
  const scopeText = scoped?.key && scoped.key !== '__all__'
    ? word(lang, 'tokScopeOne', scoped.label || scoped.key)
    : word(lang, 'tokScopeAll');
  const metaCaption = scoped ? `${scopeText} · ${word(lang, 'tokCacheMs', scoped.scanMs || 0)}` : scopeText;
  const wideControls = g.frame.width >= 960;

  const rangeBar = pillBar(
    'tok-range',
    TOKEN_RANGES.map(r => [r, word(lang, { today: 'tokRangeToday', '7d': 'tokRange7d', '30d': 'tokRange30d', all: 'tokRangeAll' }[r])]),
    range,
    (r, cx) => { v.tokensRange = r; v.hoverTokenBar = null; cx.notify(); },
    t,
  );
  const agentBar = pillBar(
    'tok-agent',
    TOKEN_AGENTS.map(a => [
      a,
      word(lang, { all: 'tokAgentAll', claude: 'tokAgentClaude', agy: 'tokAgentAgy', codex: 'tokAgentCodex', pi: 'tokAgentPi' }[a]),
      a === 'all' ? null : agentColor(a, t),
    ]),
    v.tokensAgent || 'all',
    (a, cx) => { v.tokensAgent = a; v.hoverTokenBar = null; cx.notify(); },
    t,
    { compact: true },
  );

  const iconBtn = (id, iconName, tipKey, spin, action) => h_flex().id(id).size(28).flex_none().rounded(7)
    .items_center().justify_center().cursor_pointer().bg(t.surface).text_color(t.muted)
    .hover(s => s.bg(t.raised).text_color(t.foreground))
    .accessibility_label(word(lang, tipKey))
    .on_click((_e, cx) => { cx.stop_propagation(); action(cx); })
    .child(svg(ICON(iconName)).size(14).when(spin, el => el.spin(900)));

  const header = h_flex().w_full().flex_wrap().justify_between().items_center().gap(10)
    .child(h_flex().flex_wrap().items_center().gap(12)
      .child(h_flex().items_baseline().gap(8)
        .child(div().text_size(14.5).font_semibold().text_color(t.foreground).child(word(lang, 'tokAnalytics')))
        .child(div().text_size(12).text_color(t.dim).child(metaCaption)))
      .child(rangeBar)
      .child(agentBar))
    .child(h_flex().items_center().gap(8).flex_none()
      .when(wideControls, el => el.child(div().text_size(11.5).text_color(t.dim).child(word(lang, 'tokDedupHint'))))
      .child(iconBtn('tok-refresh', 'refresh', 'tokRefreshTip', Boolean(v.tokensLoading), cx => v.refreshTokens(cx, { force: true })))
      .child(iconBtn('tok-collapse', 'chevron-up', 'tokCollapseTip', false, cx => v.toggleTokens(cx))));

  const body = (g.frame.width >= 1040 ? h_flex().gap(12).items_stretch() : v_flex().gap(12))
    .w_full()
    .child(renderChartCard(v, t, view))
    .child(renderBreakdownCard(v, t, view));

  return wrap.child(
    v_flex().id('token-shelf-panel').w_full().gap(12).pt(6)
      .child(header)
      .child(renderKpiCards(v, t, view.kpi, view.pm, g.frame.width))
      .child(body),
  );
}
