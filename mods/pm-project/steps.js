// Shared Steps Card UI component (detail Steps card + Threads & Board compact hover cards).
// Pure UI builder with zero direct imports from gpui-kit/gpui-base/herdr so Node tests can import it directly.
// Keep mods/pm-project/steps.js and mods/pm-dash/steps.js byte-for-byte identical.

import { word, withAlpha } from './model.js';

export function treeBranchList(ui, items, {
  indent = 20,
  stemX = 7,
  curveSize = 20,
  strokeW = 1.5,
  curveStart = 4,
  gap = 2,
  wireColor,
  treeBranchIcon,
} = {}) {
  const { div, svg, v_flex } = ui;
  return v_flex().w_full().min_w(0).gap(gap).children(items.map((el, i) => {
    const hasNext = i < items.length - 1;
    return div().relative().w_full().min_w(0).pl(indent)
      .when(hasNext, box => box.child(div().absolute().left(stemX - strokeW / 2).top(curveStart).bottom(-gap).w(strokeW).bg(wireColor)))
      .child(svg(treeBranchIcon).size(curveSize).absolute().left(0).top(0).text_color(wireColor))
      .child(el);
  }));
}

export function renderStepsCard({
  ui,
  steps,
  theme: t,
  lang,
  icons,
  compact = false,
  framed = !compact,
  scale = 1,
  cardId = '',
  stepIdPrefix = '',
  headerMeta = '',
  spinning = false,
  reviewSpinning = spinning,
  subSpinning = spinning,
  // Interactive options (ignored when compact === true):
  isSubOpen = null,
  onToggleSub = null,
  canClickReview = false,
  reviewOpen = false,
  onClickReview = null,
}) {
  if (!steps || !Array.isArray(steps.steps) || !steps.steps.length) return null;
  const { div, svg, h_flex, v_flex, withTip } = ui;
  const tip = (key, el, text, opts) => (withTip && text ? withTip(key, el, text, opts) : el);
  const interactive = !compact;
  const sc = compact ? (scale || 1) : 1;
  const px = n => n * sc;
  const font = n => Math.max(10, px(n));
  const wireColor = t.input || t.border;
  const doneColor = t.ansi2 ?? t.working;
  const markSize = compact ? Math.max(10, px(11)) : 12;
  const todoSize = compact ? Math.max(7, px(8)) : 8.5;
  const subMarkSize = compact ? Math.max(9, px(10)) : 10.5;
  const subTodoSize = compact ? Math.max(6, px(6.5)) : 7;
  const lineH = compact ? Math.max(14, px(16)) : 18;
  const subLineH = compact ? Math.max(13, px(15)) : 16;

  const renderStepMark = s => {
    if (s.state === 'done') return svg(icons.checkMark).size(markSize).flex_none().text_color(doneColor);
    if (s.state === 'doing') {
      const isReview = s.anchor === 'review';
      const c = isReview ? t.accent
        : (steps.postGate && s.anchor === 'custom' ? (t.working ?? t.ansi3 ?? t.accent) : doneColor);
      const spin = isReview ? reviewSpinning : spinning;
      return svg(icons.spinner).size(markSize).flex_none().text_color(c).when(spin, sp => sp.spin(900));
    }
    return div().size(todoSize).flex_none().rounded_full().border(Math.max(1, px(1.3))).border_color(t.border);
  };

  const renderSubstepMark = sub => {
    if (sub.state === 'done') return svg(icons.checkMark).size(subMarkSize).flex_none().text_color(doneColor);
    if (sub.state === 'doing') return svg(icons.spinner).size(subMarkSize).flex_none().text_color(doneColor).when(subSpinning, sp => sp.spin(900));
    return div().size(subTodoSize).flex_none().rounded_full().border(Math.max(1, px(1.2))).border_color(t.border);
  };

  const planPolicy = steps.autoReview
    ? { text: word(lang, 'planAutoReview'), tip: word(lang, 'planAutoReviewTip'), color: t.accent }
    : steps.noReview
      ? { text: word(lang, 'planNoReview'), tip: word(lang, 'planNoReviewTip'), color: t.dim }
      : null;

  const header = h_flex().w_full().min_w(0).pl(compact ? px(2) : 2).pr(compact ? px(2) : 6).gap(px(compact ? 5 : 6)).items_center()
    .child(div().flex_none().text_size(compact ? font(11) : 11.5).font_semibold().text_color(t.muted).child(word(lang, 'planTitle')))
    .when(Boolean(headerMeta), el => el.child(div().flex_1().min_w(0).truncate()
      .font_family('monospace').text_size(font(10)).text_color(t.dim).child(headerMeta)))
    .when(!headerMeta, el => el.child(div().flex_1().min_w(0)))
    .when(steps.foldedRounds > 0, el => el.child(div().flex_none().px(px(compact ? 4 : 5)).py(px(1)).rounded(px(4)).bg(t.raised)
      .font_family('monospace').text_size(compact ? font(10) : 10.5).text_color(t.dim).child(steps.foldedLabel)))
    .when(Boolean(planPolicy), el => {
      const pill = div().flex_none().px(px(compact ? 4 : 5)).py(px(1)).rounded(px(4))
        .bg(withAlpha(planPolicy.color, .12)).text_size(compact ? font(10) : 10.5).text_color(planPolicy.color)
        .child(planPolicy.text);
      return el.child(interactive && planPolicy.tip
        ? tip(`${cardId || 'steps'}-policy`, pill, planPolicy.tip, { panel: true, placement: 'below-right', wrap: true, flexNone: true })
        : pill);
    })
    .child(div().flex_none().font_family('monospace').text_size(compact ? font(10.5) : 11).text_color(t.muted).child(steps.progress));

  const stepEls = steps.steps.map(s => {
    const hasSubs = Boolean(s.substeps?.length);
    const subOpen = hasSubs && (interactive && isSubOpen ? Boolean(isSubOpen(s)) : s.state === 'doing');
    const clickableReview = interactive && s.anchor === 'review' && Boolean(canClickReview) && Boolean(onClickReview);
    const revWinOpen = interactive && s.anchor === 'review' && Boolean(reviewOpen);
    const rightMeta = s.right || s.commit || '';
    const stepLabel = s.text || s.shortText;

    const stepTip = clickableReview
      ? word(lang, 'detailReviewStepTip')
      : (interactive && s.tip ? s.tip : '');
    const stepRowEl = h_flex()
      .when(Boolean(stepIdPrefix), el => el.id(`${stepIdPrefix}-${s.index}`))
      .w_full().min_w(0).overflow_hidden()
      .min_h(compact ? Math.max(19, px(21)) : 24)
      .px(compact ? px(5) : 6).py(compact ? px(1.5) : 2).gap(compact ? px(6) : 7)
      .rounded(compact ? px(5) : 6).items_start()
      .when(s.state === 'doing' && !revWinOpen, el => el.bg(withAlpha(s.anchor === 'review' ? t.accent : t.foreground, .05)))
      .when(revWinOpen, el => el.bg(withAlpha(t.accent, .14)))
      .when(clickableReview, el => el.cursor_pointer().hover(h => h.bg(t.hover))
        .accessibility_label(word(lang, 'detailReviewStepTip'))
        .on_click((_e, cx) => { cx.stop_propagation(); onClickReview(cx); }))
      .child(h_flex().w(compact ? Math.max(12, px(13)) : 14).h(lineH).flex_none().items_center().justify_center()
        .child(renderStepMark(s)))
      .child(div().flex_1().min_w(0).whitespace_normal()
        .text_size(compact ? font(12) : 12.5).line_height(`${lineH}px`)
        .font_weight(s.state === 'doing' ? 500 : 400)
        .text_color(s.state === 'todo' ? t.muted : t.foreground)
        .child(stepLabel))
      .when(s.round > 1, el => el.child(h_flex().h(lineH).flex_none().items_center()
        .child(div().px(px(compact ? 4 : 5)).rounded(px(4)).bg(withAlpha(t.accent, .14))
          .font_family('monospace').text_size(compact ? font(10) : 10.5).text_color(t.accent)
          .child(word(lang, 'planRound', s.round)))))
      .when(Boolean(rightMeta), el => el.child(h_flex().h(lineH).min_w(0).max_w('40%').flex_shrink_1().items_center().overflow_hidden()
        .child(div().min_w(0).truncate().font_family('monospace').text_size(compact ? font(10) : 10.5)
          .text_color(t.dim).child(rightMeta))))
      .when(clickableReview && Boolean(icons.windowPop), el => el.child(h_flex().h(lineH).flex_none().items_center()
        .child(svg(icons.windowPop).size(11.5).flex_none().text_color(revWinOpen ? t.accent : t.dim))))
      .when(hasSubs, el => el.child(h_flex().h(lineH).flex_none().items_center()
        .child(interactive && onToggleSub
          ? tip(`substep-fold-${s.index}`, h_flex().id(`substep-fold-${s.index}`).h(18).px(5).gap(3).rounded(4)
              .items_center().cursor_pointer().bg(t.raised).hover(h => h.bg(t.hover))
              .on_click((_e, cx) => { cx.stop_propagation(); onToggleSub(s, cx); })
              .child(div().font_family('monospace').text_size(10.5).text_color(t.muted)
                .child(`${s.subProgress.done}/${s.subProgress.total}`))
              .child(svg(subOpen ? icons.expand : icons.chevron).size(9.5).flex_none().text_color(t.dim)),
              word(lang, 'substepsFoldTip', s.subProgress.done, s.subProgress.total),
              { panel: true, placement: 'above-right' })
          : div().px(px(4)).py(px(1)).rounded(px(4)).bg(withAlpha(t.foreground, .07))
              .font_family('monospace').text_size(font(10)).text_color(t.muted)
              .child(`${s.subProgress.done}/${s.subProgress.total}`))));
    const stepRow = stepTip
      ? tip(`${stepIdPrefix || 'plan-step'}-${s.index}`, stepRowEl, stepTip, { panel: true, placement: 'above-left', wrap: true, full: true })
      : stepRowEl;

    if (!hasSubs || !subOpen) return stepRow;
    const subItems = s.substeps.map(sub => {
      const splitNote = Boolean(sub.note) && !sub.shortText.endsWith('…');
      const subLabel = splitNote ? sub.shortText : (sub.text || sub.shortText);
      const subEl = h_flex()
        .when(Boolean(stepIdPrefix), el => el.id(`plan-substep-${s.index}-${sub.index}`))
        .w_full().min_w(0).overflow_hidden()
        .min_h(compact ? Math.max(17, px(19)) : 21)
        .px(compact ? px(4) : 6).py(compact ? px(1) : 1.5).gap(compact ? px(5) : 6)
        .rounded(px(5)).items_start()
        .child(h_flex().w(compact ? Math.max(10, px(11)) : 12).h(subLineH).flex_none().items_center().justify_center()
          .child(renderSubstepMark(sub)))
        .child(div().flex_1().min_w(0).whitespace_normal()
          .text_size(compact ? font(11) : 11.8).line_height(`${subLineH}px`)
          .text_color(sub.state === 'doing' ? t.foreground : sub.state === 'done' ? t.muted : t.dim)
          .child(subLabel))
        .when(splitNote, el => el.child(h_flex().h(subLineH).min_w(0).max_w('40%').flex_shrink_1().items_center().overflow_hidden()
          .child(div().min_w(0).truncate().text_size(compact ? font(10) : 10.5).text_color(t.dim).child(sub.note))));
      return interactive && sub.tip
        ? tip(`plan-substep-${s.index}-${sub.index}`, subEl, sub.tip, { panel: true, placement: 'above-left', wrap: true, full: true })
        : subEl;
    });
    return v_flex().w_full().min_w(0).gap(compact ? px(1.5) : 2)
      .child(stepRow)
      .child(div().w_full().min_w(0).pl(compact ? px(4) : 5).child(treeBranchList(ui, subItems, {
        indent: compact ? px(15) : 18,
        stemX: compact ? px(5) : 6,
        curveSize: compact ? px(15) : 18,
        strokeW: compact ? Math.max(1, px(1.2)) : 1.4,
        curveStart: compact ? px(2.5) : 3,
        gap: compact ? px(1.5) : 2,
        wireColor,
        treeBranchIcon: icons.treeBranch,
      })));
  });

  return v_flex()
    .when(Boolean(cardId), el => el.id(cardId))
    .w_full().min_w(0).flex_none().gap(compact ? px(4) : 6)
    .when(framed, el => el.rounded(10).p(10).bg(t.surface).border_1().border_color(t.border))
    .child(header)
    .child(v_flex().w_full().min_w(0).gap(compact ? px(2) : 3).children(stepEls));
}

export function renderDepsCard({
  ui,
  deps,
  theme: t,
  lang,
  icons,
  compact = false,
  framed = !compact,
  scale = 1,
  cardId = '',
  rowIdPrefix = '',
  headerMeta = '',
  animate = true,
  onSelect = null,
}) {
  if (!deps || !Array.isArray(deps.items) || !deps.items.length) return null;
  const { div, svg, h_flex, v_flex, withTip } = ui;
  const tip = (key, el, text, opts) => (withTip && text ? withTip(key, el, text, opts) : el);
  const sc = compact ? (scale || 1) : 1;
  const px = n => n * sc;
  const font = n => Math.max(10, px(n));
  const doneColor = t.ansi2 ?? t.working;
  const markSize = compact ? Math.max(10, px(11)) : 12;
  const todoSize = compact ? Math.max(7, px(8)) : 8.5;
  const dotSize = compact ? Math.max(6, px(7)) : 7.5;
  const ringSize = compact ? Math.max(9, px(10)) : 11;
  const innerDot = compact ? Math.max(3.5, px(4)) : 4.5;
  const lineH = compact ? Math.max(14, px(16)) : 18;

  const renderDepMark = item => {
    if (item.isMet) return svg(icons.checkMark).size(markSize).flex_none().text_color(doneColor);
    if (item.isBlocked) return div().size(dotSize).flex_none().rounded_full().bg(t.blocked);
    if (item.isReview) {
      if (item.isReviewWorking) {
        return svg(icons.spinner).size(markSize).flex_none().text_color(t.accent).when(animate, sp => sp.spin(900));
      }
      return h_flex().size(ringSize).flex_none().rounded_full().border(Math.max(1, px(1.3))).border_color(t.accent)
        .items_center().justify_center()
        .child(div().size(innerDot).rounded_full().bg(t.accent));
    }
    if (item.isWorking) {
      return svg(icons.spinner).size(markSize).flex_none().text_color(doneColor).when(animate, sp => sp.spin(900));
    }
    return div().size(todoSize).flex_none().rounded_full().border(Math.max(1, px(1.3)))
      .border_color(item.isBroken ? t.blocked : t.border);
  };

  const header = h_flex().w_full().min_w(0).pl(compact ? px(2) : 2).pr(compact ? px(2) : 6).gap(px(compact ? 5 : 6)).items_center()
    .child(div().flex_none().text_size(compact ? font(11) : 11.5).font_semibold().text_color(t.muted).child(word(lang, 'depsTitle')))
    .when(Boolean(headerMeta), el => el.child(div().flex_1().min_w(0).truncate()
      .font_family('monospace').text_size(font(10)).text_color(t.dim).child(headerMeta)))
    .when(!headerMeta, el => el.child(div().flex_1().min_w(0)))
    .when(deps.ready, el => el.child(div().flex_none().px(px(compact ? 5 : 6)).py(px(1)).rounded(px(4))
      .bg(withAlpha(doneColor, .14)).text_size(compact ? font(10) : 10.5).font_medium().text_color(doneColor)
      .child(word(lang, 'depsReady'))))
    .child(div().flex_none().font_family('monospace').text_size(compact ? font(10.5) : 11)
      .text_color(deps.ready ? doneColor : t.muted).child(deps.progress));

  const rowEls = deps.items.map((item, idx) => {
    const clickable = Boolean(onSelect) && Boolean(item.clickable);
    const brokenTag = item.state === 'abandoned' ? word(lang, 'depsAbandoned')
      : item.state === 'missing' ? word(lang, 'depsMissing') : '';
    const rowEl = h_flex()
      .when(Boolean(rowIdPrefix), el => el.id(`${rowIdPrefix}-${item.id}`))
      .when(!rowIdPrefix && clickable, el => el.id(`dep-jump-${idx}-${item.id}`))
      .min_h(compact ? Math.max(19, px(21)) : 24)
      .px(compact ? px(5) : 6).py(compact ? px(1.5) : 2).gap(compact ? px(6) : 7)
      .rounded(compact ? px(5) : 6).items_start()
      .when(clickable, el => el.cursor_pointer().hover(h => h.bg(t.hover))
        .accessibility_label(word(lang, 'depsJumpTip', item.title))
        .on_click((_e, cx) => { cx.stop_propagation(); onSelect(item, cx); }))
      .child(h_flex().w(compact ? Math.max(12, px(13)) : 14).h(lineH).flex_none().items_center().justify_center()
        .child(renderDepMark(item)))
      .child(div().flex_1().min_w(0).whitespace_normal()
        .text_size(compact ? font(12) : 12.5).line_height(`${lineH}px`)
        .text_color(item.isMet ? t.muted : item.isBroken ? t.dim : t.foreground)
        .when(item.state === 'abandoned', el => el.line_through())
        .child(item.title))
      .when(Boolean(brokenTag), el => el.child(h_flex().h(lineH).flex_none().items_center()
        .child(div().text_size(compact ? font(10) : 10.5).text_color(t.blocked).child(brokenTag))))
      .when(clickable && Boolean(icons.chevron), el => el.child(h_flex().h(lineH).flex_none().items_center()
        .child(svg(icons.chevron).size(compact ? Math.max(9, px(9.5)) : 10).flex_none().text_color(t.dim))));
    return clickable && !compact
      ? tip(`${rowIdPrefix || 'dep'}-${item.id}`, rowEl, word(lang, 'depsJumpTip', item.title), { panel: true, placement: 'above-left' })
      : rowEl;
  });

  return v_flex()
    .when(Boolean(cardId), el => el.id(cardId))
    .w_full().min_w(0).flex_none().gap(compact ? px(4) : 6)
    .when(framed, el => el.rounded(10).p(10).bg(t.surface).border_1().border_color(t.border))
    .child(header)
    .child(v_flex().w_full().min_w(0).gap(compact ? px(2) : 3).children(rowEls));
}
