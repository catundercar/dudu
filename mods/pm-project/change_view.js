// Thread Change View component (Interface H: commits -> files -> single-file diff).
// Pure UI builder with zero direct imports from gpui-kit/gpui-base/herdr so Node tests can import it directly.

import {
  word, withAlpha, isDarkTheme,
  groupDiffHunks, splitFilePath, changeStateMessage, formatCommitDate, diffLineNumWidth,
} from './model.js';

function statusTone(status, t) {
  const addColor = t.ansi2 || t.working || t.accent;
  const delColor = t.ansi1 || t.blocked;
  const modColor = t.ansi3 || t.accent;
  switch (status) {
    case 'A': return addColor;
    case 'D': return delColor;
    case 'R':
    case 'C': return t.accent || modColor;
    case 'T': return t.muted || t.dim;
    default: return modColor;
  }
}

function statCounts(ins, dels, t, size = 11.5) {
  const addColor = t.ansi2 || t.working || t.accent;
  const delColor = t.ansi1 || t.blocked;
  return { addColor, delColor, ins: Number(ins) || 0, dels: Number(dels) || 0, size };
}

export function renderThreadChangeView({
  ui,
  theme: t,
  lang,
  today = '',
  width,
  state,
  task,
  scrollHandle,
  actions,
}) {
  const { div, svg, v_flex, h_flex, icon, iconButton, SPINNER, withTip } = ui;
  const tip = (key, el, text, opts) => (withTip && text ? withTip(key, el, text, opts) : el);
  const st = state || {};
  const level = st.level || 'commits';
  const summary = st.summary || null;
  const dark = isDarkTheme(t);
  const addColor = t.ansi2 || t.working || t.accent;
  const delColor = t.ansi1 || t.blocked;

  const backTip = level === 'diff'
    ? word(lang, 'changeBackFiles')
    : level === 'files'
      ? word(lang, 'changeBackCommits')
      : word(lang, 'changeBackDetail');

  let headerTitle = summary?.branch || task?.branch || word(lang, 'changeTitle');
  if (level === 'files') {
    if (st.scope === 'commit') {
      const c = st.commitData?.commit || (summary?.commits || []).find(k => k.hash === st.commitHash) || summary?.recorded_commit;
      headerTitle = c ? `${c.short || String(c.hash || '').slice(0, 7)} · ${c.subject || ''}` : String(st.commitHash || '').slice(0, 7);
    } else {
      headerTitle = word(lang, 'changeAllScope');
    }
  } else if (level === 'diff') {
    const fp = splitFilePath(st.filePath || st.diffData?.file?.path || '');
    headerTitle = fp.name || st.filePath || word(lang, 'changeTitle');
  }

  const loadingNow = (level === 'commits' && st.summaryLoading)
    || (level === 'files' && st.scope === 'commit' && st.commitLoading)
    || (level === 'diff' && st.diffLoading);

  const grouped = level === 'diff' && st.diffData && !st.diffData.binary
    ? groupDiffHunks(st.diffData.lines || [])
    : { meta: [], hunks: [] };
  const hunks = grouped.hunks;
  const foldedMap = st.foldedHunks || {};
  const allFolded = hunks.length > 0 && hunks.every(h => Boolean(foldedMap[h.id]));

  const topBar = h_flex().flex_none().px(14).pt(6).pb(6).gap(4).items_center().border_b(1).border_color(t.border)
    .child(iconButton('change-back', 'back', backTip, actions.onBack, t, 15, { panel: true, placement: 'below-left' }))
    .child(tip('change-header-title', div().id('change-header-title').w_full().truncate().text_size(13.5).font_semibold().text_color(t.foreground)
      .child(headerTitle), headerTitle, { panel: true, placement: 'below-left', wrap: true, flex1: true }))
    .when(level === 'diff' && hunks.length > 0, el => el.child(iconButton(
      'change-toggle-all',
      allFolded ? 'expand' : 'collapse',
      word(lang, allFolded ? 'changeExpandAll' : 'changeCollapseAll'),
      cx => actions.onToggleAllHunks(hunks, cx),
      t,
      14,
      { panel: true, placement: 'below-right' },
    )))
    .child(loadingNow
      ? tip('change-refresh-busy', h_flex().id('change-refresh-busy').size(32).flex_none().items_center().justify_center()
          .accessibility_label(word(lang, 'changeRefresh'))
          .child(svg(SPINNER).size(14).flex_none().text_color(t.muted).spin(900)),
          word(lang, 'changeRefresh'), { panel: true, placement: 'below-right' })
      : iconButton('change-refresh', 'refresh', word(lang, 'changeRefresh'), actions.onRefresh, t, 14, { panel: true, placement: 'below-right' }));

  const renderCounts = (ins, dels, size = 11.5) => {
    const sc = statCounts(ins, dels, t, size);
    return h_flex().flex_none().gap(5).items_center().font_family('monospace').text_size(sc.size)
      .child(div().text_color(sc.addColor).child(`+${sc.ins}`))
      .child(div().text_color(sc.delColor).child(`−${sc.dels}`));
  };

  const renderCommitRow = (id, c, onClick, baseName = '') => {
    const sub = [c.author, formatCommitDate(c.date, today), word(lang, 'changeFilesCount', c.files || 0)]
      .filter(Boolean).join(' · ');
    const badge = c.merges_base
      ? word(lang, 'changeMergeBaseBadge', baseName || 'main')
      : c.merge
        ? word(lang, 'changeMergeBadge')
        : '';
    const tipText = [c.short || String(c.hash || '').slice(0, 7), badge, c.subject, sub].filter(Boolean).join('\n');
    return tip(id, h_flex().id(id).w_full().px(10).py(8).gap(8).rounded(9).items_start()
      .bg(t.surface).border_1().border_color(t.border).cursor_pointer()
      .hover(s => s.bg(t.hover))
      .accessibility_label(c.subject || c.short || '')
      .on_click((_e, cx) => onClick(c, cx))
      .child(div().flex_none().pt(1).font_family('monospace').text_size(11.5).text_color(t.dim)
        .child(c.short || String(c.hash || '').slice(0, 7)))
      .child(v_flex().flex_1().min_w(0).gap(2)
        .child(h_flex().w_full().gap(6).items_center()
          .child(div().flex_1().min_w(0).truncate().text_size(12.5).font_medium().text_color(t.foreground).child(c.subject || ''))
          .when(Boolean(badge), el => el.child(h_flex().flex_none().h(17).px(5).rounded(5).items_center()
            .bg(t.raised).border_1().border_color(t.border)
            .text_size(10).text_color(t.muted).child(badge))))
        .child(div().w_full().truncate().text_size(11).text_color(t.dim).child(sub)))
      .child(h_flex().flex_none().pt(1).gap(6).items_center()
        .child(renderCounts(c.insertions, c.deletions, 11))
        .child(icon('chevron', 12).text_color(t.dim))), tipText, { panel: true, placement: 'above-left' });
  };

  const renderFileRow = (f, idx) => {
    const fp = splitFilePath(f.path);
    const status = String(f.status || 'M').slice(0, 1);
    const sColor = statusTone(status, t);
    const sTip = word(lang, `changeStatus_${status}`) || status;
    const pathTip = f.old_path ? `${f.old_path} → ${f.path}` : f.path;
    return tip(`change-file-${idx}`, h_flex().id(`change-file-${idx}`).w_full().px(10).py(7).gap(8).rounded(9).items_center()
      .bg(t.surface).border_1().border_color(t.border).cursor_pointer()
      .hover(s => s.bg(t.hover))
      .accessibility_label(f.path)
      .on_click((_e, cx) => actions.onPickFile(f, cx))
      .child(tip(`change-file-${idx}-status`, h_flex().id(`change-file-${idx}-status`).flex_none().size(20).rounded(6).items_center().justify_center()
        .bg(withAlpha(sColor, 0.14)).text_color(sColor).font_family('monospace').text_size(11).font_semibold()
        .child(status), sTip, { panel: true, placement: 'above-left' }))
      .child(v_flex().flex_1().min_w(0).gap(1)
        .child(div().w_full().truncate().text_size(12.5).font_medium().text_color(t.foreground).child(fp.name || f.path))
        .when(Boolean(fp.dir || f.old_path), el => el.child(div().w_full().truncate().font_family('monospace')
          .text_size(10.5).text_color(t.dim).child(f.old_path ? `${f.old_path} →` : fp.dir))))
      .child(h_flex().flex_none().gap(6).items_center()
        .when(Boolean(f.binary), el => el.child(h_flex().h(18).px(6).rounded(5).items_center()
          .bg(t.raised).text_size(10.5).text_color(t.muted).child(word(lang, 'changeBinaryBadge'))))
        .when(!f.binary, el => el.child(renderCounts(f.insertions, f.deletions, 11)))
        .child(icon('chevron', 12).text_color(t.dim))), pathTip, { panel: true, placement: 'above-left' });
  };

  const bodyChildren = [];

  if (level === 'commits') {
    if (st.summaryLoading && !summary) {
      bodyChildren.push(h_flex().pt(8).gap(8).items_center().text_size(12.5).text_color(t.dim)
        .child(svg(SPINNER).size(14).flex_none().spin(900)).child(word(lang, 'changeLoading')));
    } else if (st.summaryError && !summary) {
      bodyChildren.push(div().id('change-error').p(10).rounded(9).bg(withAlpha(delColor, 0.10))
        .border_1().border_color(withAlpha(delColor, 0.28)).whitespace_normal().text_size(12.5)
        .text_color(delColor).child(word(lang, 'changeError', st.summaryError)));
    } else if (summary) {
      if (summary.state !== 'ok') {
        bodyChildren.push(div().id('change-state-note').p(10).rounded(9).bg(t.surface)
          .border_1().border_color(t.border).whitespace_normal().text_size(12.5).text_color(t.muted)
          .child(changeStateMessage(lang, summary)));
        if (summary.uncommitted > 0) {
          bodyChildren.push(div().id('change-uncommitted').px(10).py(6).rounded(8)
            .bg(withAlpha(t.ansi3 || t.accent, 0.12)).text_size(11.5).text_color(t.foreground)
            .whitespace_normal().child(word(lang, 'changeUncommitted', summary.uncommitted)));
        }
        if (summary.recorded_commit) {
          bodyChildren.push(div().pt(4).text_size(11.5).text_color(t.dim).child(word(lang, 'changeRecordedHint')));
          bodyChildren.push(renderCommitRow('change-recorded-commit', summary.recorded_commit, actions.onPickCommit, summary.base));
        }
      } else {
        const allCommits = summary.commits || [];
        const ownCommits = allCommits.filter(c => !c.merges_base);
        const baseMerges = allCommits.filter(c => Boolean(c.merges_base));

        bodyChildren.push(h_flex().id('change-branch-meta').flex_wrap().gap(6).items_center().text_size(11.5).text_color(t.dim)
          .child(div().font_family('monospace').text_color(t.foreground).child(`${summary.branch} → ${summary.base}`))
          .child(div().child('·'))
          .child(div().child(word(lang, 'changeCommitsCount', ownCommits.length)))
          .child(div().child('·'))
          .child(div().child(word(lang, 'changeFilesCount', (summary.files || []).length)))
          .child(renderCounts(summary.insertions, summary.deletions, 11.5)));

        if (summary.uncommitted > 0) {
          bodyChildren.push(div().id('change-uncommitted').px(10).py(6).rounded(8)
            .bg(withAlpha(t.ansi3 || t.accent, 0.12)).text_size(11.5).text_color(t.foreground)
            .whitespace_normal().child(word(lang, 'changeUncommitted', summary.uncommitted)));
        }

        bodyChildren.push(tip('change-scope-all', h_flex().id('change-scope-all').w_full().px(10).py(9).gap(8).rounded(9).items_center()
          .bg(t.raised).border_1().border_color(t.border).cursor_pointer()
          .hover(s => s.bg(t.hover))
          .accessibility_label(word(lang, 'changeAllTitle'))
          .on_click((_e, cx) => actions.onPickAll(cx))
          .child(icon('diff', 14).text_color(t.accent))
          .child(v_flex().flex_1().min_w(0).gap(1)
            .child(div().text_size(12.5).font_semibold().text_color(t.foreground).child(word(lang, 'changeAllTitle')))
            .child(div().text_size(11).text_color(t.dim)
              .child(word(lang, 'changeFilesCount', (summary.files || []).length))))
          .child(renderCounts(summary.insertions, summary.deletions, 11.5))
          .child(icon('chevron', 12).text_color(t.dim)), word(lang, 'changeAllTitle'), { panel: true, placement: 'above-left' }));

        for (const c of ownCommits) {
          bodyChildren.push(renderCommitRow(`change-commit-${c.short || String(c.hash || '').slice(0, 7)}`, c, actions.onPickCommit, summary.base));
        }

        if (baseMerges.length > 0) {
          const mergesOpen = Boolean(st.showBaseMerges);
          const foldLabel = word(lang, 'changeBaseMergesFold', baseMerges.length, summary.base || 'main');
          bodyChildren.push(tip('change-base-merges-toggle', h_flex().id('change-base-merges-toggle').w_full().px(10).py(6).gap(6).rounded(8).items_center()
            .cursor_pointer().text_size(11.5).text_color(t.muted).hover(s => s.bg(t.hover).text_color(t.foreground))
            .accessibility_label(foldLabel)
            .on_click((_e, cx) => actions.onToggleBaseMerges(cx))
            .child(icon(mergesOpen ? 'expand' : 'chevron', 12).text_color(t.dim))
            .child(div().flex_1().min_w(0).truncate().child(foldLabel)), foldLabel, { panel: true, placement: 'above-left' }));
          if (mergesOpen) {
            for (const c of baseMerges) {
              bodyChildren.push(renderCommitRow(`change-commit-${c.short || String(c.hash || '').slice(0, 7)}`, c, actions.onPickCommit, summary.base));
            }
          }
        }

        if (summary.more_commits) {
          bodyChildren.push(div().px(4).pt(2).whitespace_normal().text_size(11.5).text_color(t.dim)
            .child(word(lang, 'changeMoreCommits')));
        }
      }
    }
  } else if (level === 'files') {
    const isCommit = st.scope === 'commit';
    const commitMeta = isCommit ? (st.commitData?.commit || (summary?.commits || []).find(k => k.hash === st.commitHash) || summary?.recorded_commit) : null;
    const files = isCommit ? (st.commitData?.files || null) : (summary?.files || []);
    const ins = isCommit ? (st.commitData?.insertions ?? commitMeta?.insertions ?? 0) : (summary?.insertions ?? 0);
    const dels = isCommit ? (st.commitData?.deletions ?? commitMeta?.deletions ?? 0) : (summary?.deletions ?? 0);

    if (isCommit && commitMeta) {
      if (commitMeta.subject) {
        bodyChildren.push(div().whitespace_normal().text_size(12.5).font_medium().text_color(t.foreground)
          .child(commitMeta.subject));
      }
      bodyChildren.push(h_flex().flex_wrap().gap(6).items_center().text_size(11.5).text_color(t.dim)
        .child(div().font_family('monospace').text_color(t.muted).child(commitMeta.short || String(commitMeta.hash || '').slice(0, 7)))
        .when(Boolean(commitMeta.author), el => el.child(div().child(commitMeta.author)))
        .when(Boolean(commitMeta.date), el => el.child(div().child(formatCommitDate(commitMeta.date, today))))
        .when(Array.isArray(files), el => el.child(div().child(word(lang, 'changeFilesCount', files.length))))
        .child(renderCounts(ins, dels, 11.5)));
      if (commitMeta.merge) {
        bodyChildren.push(div().id('change-merge-note').px(10).py(7).rounded(8).bg(t.surface)
          .border_1().border_color(t.border).whitespace_normal().text_size(11.5).text_color(t.muted)
          .child(commitMeta.merges_base
            ? word(lang, 'changeMergeBaseNote', summary?.base || 'main')
            : word(lang, 'changeMergeNote')));
      }
    } else if (!isCommit && summary) {
      bodyChildren.push(h_flex().flex_wrap().gap(6).items_center().text_size(11.5).text_color(t.dim)
        .child(div().font_family('monospace').text_color(t.foreground).child(`${summary.branch} → ${summary.base}`))
        .child(div().child('·'))
        .child(div().child(word(lang, 'changeFilesCount', (files || []).length)))
        .child(renderCounts(ins, dels, 11.5)));
    }

    if (isCommit && st.commitLoading && !Array.isArray(files)) {
      bodyChildren.push(h_flex().pt(8).gap(8).items_center().text_size(12.5).text_color(t.dim)
        .child(svg(SPINNER).size(14).flex_none().spin(900)).child(word(lang, 'changeLoadingFiles')));
    } else if (isCommit && st.commitError && !Array.isArray(files)) {
      bodyChildren.push(div().id('change-commit-error').p(10).rounded(9).bg(withAlpha(delColor, 0.10))
        .border_1().border_color(withAlpha(delColor, 0.28)).whitespace_normal().text_size(12.5)
        .text_color(delColor).child(word(lang, 'changeError', st.commitError)));
    } else if (Array.isArray(files) && files.length === 0) {
      bodyChildren.push(div().p(10).rounded(9).bg(t.surface).border_1().border_color(t.border)
        .text_size(12.5).text_color(t.muted).child(word(lang, 'changeNoFiles')));
    } else if (Array.isArray(files)) {
      files.forEach((f, idx) => bodyChildren.push(renderFileRow(f, idx)));
    }
  } else if (level === 'diff') {
    const fileInfo = st.diffData?.file || st.fileMeta || { path: st.filePath };
    const status = String(fileInfo?.status || 'M').slice(0, 1);
    const sColor = statusTone(status, t);
    const fullPath = fileInfo?.old_path ? `${fileInfo.old_path} → ${fileInfo.path}` : (fileInfo?.path || st.filePath || '');
    const loadedLines = st.diffData?.lines?.length || 0;
    const totalLines = st.diffData?.total_lines || 0;

    bodyChildren.push(v_flex().gap(4)
      .child(div().w_full().font_family('monospace').text_size(11).text_color(t.dim).whitespace_normal().child(fullPath))
      .child(h_flex().flex_wrap().gap(6).items_center().text_size(11.5).text_color(t.dim)
        .child(h_flex().flex_none().h(18).px(6).rounded(5).items_center()
          .bg(withAlpha(sColor, 0.14)).text_color(sColor).text_size(11).font_medium()
          .child(word(lang, `changeStatus_${status}`) || status))
        .when(!fileInfo?.binary && fileInfo?.insertions != null, el => el.child(renderCounts(fileInfo.insertions, fileInfo.deletions, 11.5)))
        .when(totalLines > loadedLines, el => el.child(div().text_size(11).text_color(t.muted)
          .child(word(lang, 'changeLinesShown', loadedLines, totalLines))))));

    if (st.diffData?.commit?.merge) {
      const dc = st.diffData.commit;
      bodyChildren.push(div().id('change-merge-note').px(10).py(7).rounded(8).bg(t.surface)
        .border_1().border_color(t.border).whitespace_normal().text_size(11.5).text_color(t.muted)
        .child(dc.merges_base
          ? word(lang, 'changeMergeBaseNote', st.diffData.base || summary?.base || 'main')
          : word(lang, 'changeMergeNote')));
    }

    if (st.diffLoading && !st.diffData) {
      bodyChildren.push(h_flex().pt(8).gap(8).items_center().text_size(12.5).text_color(t.dim)
        .child(svg(SPINNER).size(14).flex_none().spin(900)).child(word(lang, 'changeLoadingDiff')));
    } else if (st.diffError && !st.diffData) {
      bodyChildren.push(div().id('change-diff-error').p(10).rounded(9).bg(withAlpha(delColor, 0.10))
        .border_1().border_color(withAlpha(delColor, 0.28)).whitespace_normal().text_size(12.5)
        .text_color(delColor).child(word(lang, 'changeError', st.diffError)));
    } else if (st.diffData?.binary) {
      bodyChildren.push(div().id('change-binary-note').p(10).rounded(9).bg(t.surface)
        .border_1().border_color(t.border).text_size(12.5).text_color(t.muted)
        .child(word(lang, 'changeBinaryFile')));
    } else if (st.diffData) {
      if (grouped.meta.length > 0) {
        bodyChildren.push(v_flex().p(8).gap(2).rounded(8).bg(t.surface).border_1().border_color(t.border)
          .children(grouped.meta.map((m, i) => div().id(`change-meta-${i}`).font_family('monospace')
            .text_size(11).text_color(t.dim).whitespace_normal().child(m.text || ''))));
      }
      if (hunks.length === 0 && grouped.meta.length === 0) {
        bodyChildren.push(div().p(10).rounded(9).bg(t.surface).border_1().border_color(t.border)
          .text_size(12.5).text_color(t.muted).child(word(lang, 'changeNoDiffLines')));
      }
      const numW = diffLineNumWidth(st.diffData.lines);
      for (const h of hunks) {
        const folded = Boolean(foldedMap[h.id]);
        const hunkEl = v_flex().id(`change-hunk-${h.index}`).w_full().rounded(9).overflow_hidden().border_1().border_color(t.border)
          .bg(t.surface)
          .child(tip(`change-hunk-head-${h.index}`, h_flex().id(`change-hunk-head-${h.index}`).w_full().px(8).py(6).gap(6).items_center()
            .bg(t.raised).cursor_pointer().hover(s => s.bg(t.hover))
            .on_click((_e, cx) => actions.onToggleHunk(h.id, cx))
            .child(icon(folded ? 'chevron' : 'expand', 12).text_color(t.muted))
            .child(div().flex_1().min_w(0).truncate().font_family('monospace').text_size(11).text_color(t.muted)
              .child(h.header || `@@ #${h.index + 1} @@`))
            .child(renderCounts(h.insertions, h.deletions, 10.5)), word(lang, folded ? 'changeUnfoldHunk' : 'changeFoldHunk'), { panel: true, placement: 'above-left' }));

        if (!folded && h.lines.length > 0) {
          const lineRows = h.lines.map((line, li) => {
            const kind = line.kind || 'ctx';
            const isAdd = kind === 'add';
            const isDel = kind === 'del';
            const isMeta = kind === 'meta';
            const rowBg = isAdd
              ? withAlpha(addColor, dark ? 0.16 : 0.13)
              : isDel
                ? withAlpha(delColor, dark ? 0.16 : 0.13)
                : isMeta
                  ? t.raised
                  : null;
            const sign = isAdd ? '+' : isDel ? '−' : isMeta ? '\\' : ' ';
            const signColor = isAdd ? addColor : isDel ? delColor : t.dim;
            const textColor = isAdd || isDel ? t.foreground : isMeta ? t.dim : t.muted;
            const oldStr = line.old_line != null ? String(line.old_line) : '';
            const newStr = line.new_line != null ? String(line.new_line) : '';

            return h_flex().id(`change-line-${h.index}-${li}`).w_full().px(6).py(1).gap(4).items_start()
              .when(Boolean(rowBg), el => el.bg(rowBg))
              .font_family('monospace').text_size(11.5)
              .child(div().w(numW).flex_none().whitespace_nowrap().text_right().text_color(t.dim).child(oldStr))
              .child(div().w(numW).flex_none().whitespace_nowrap().text_right().text_color(t.dim).child(newStr))
              .child(div().w(10).flex_none().text_color(signColor).child(sign))
              .child(div().flex_1().min_w(0).whitespace_normal().text_color(textColor)
                .child(line.text ? line.text : ' '));
          });
          hunkEl.child(v_flex().w_full().py(2).border_t(1).border_color(t.border).children(lineRows));
        }
        bodyChildren.push(hunkEl);
      }

      if (st.diffData.truncated_lines) {
        bodyChildren.push(div().px(4).text_size(11.5).text_color(t.dim).whitespace_normal()
          .child(word(lang, 'changeTruncatedLines')));
      }
      if (st.diffData.truncated) {
        bodyChildren.push(div().id('change-truncated-bytes').px(10).py(6).rounded(8)
          .bg(withAlpha(t.ansi3 || t.accent, 0.12)).text_size(11.5).text_color(t.foreground)
          .whitespace_normal().child(word(lang, 'changeTruncatedBytes')));
      }
      if (st.diffData.has_more) {
        const remaining = Math.max(0, (st.diffData.total_lines || 0) - loadedLines);
        const busyMore = Boolean(st.diffLoadingMore);
        const label = busyMore ? word(lang, 'changeLoadingMore') : word(lang, 'changeLoadMore', remaining);
        bodyChildren.push(tip('change-load-more', h_flex().id('change-load-more').h(32).px(10).gap(7).rounded(8).items_center()
          .bg(t.surface).border_1().border_color(t.border)
          .when(!busyMore, el => el.cursor_pointer().hover(s => s.bg(t.hover).text_color(t.foreground))
            .on_click((_e, cx) => actions.onLoadMore(cx)))
          .text_size(12).text_color(t.muted)
          .accessibility_label(label)
          .child(busyMore ? svg(SPINNER).size(13).flex_none().spin(900) : icon('expand', 13))
          .child(label), label, { panel: true, placement: 'above-left' }));
      }
      if (st.diffError) {
        bodyChildren.push(div().text_size(11.5).text_color(delColor).whitespace_normal()
          .child(word(lang, 'changeError', st.diffError)));
      }
    }
  }

  return v_flex().id('thread-change-view').w(width).h_full().flex_none()
    .bg(t.chrome).border_l(1).border_color(t.border)
    .child(topBar)
    .child(v_flex().id('change-body').flex_1().min_h(0).px(16).pt(10).pb(20).gap(8).overflow_y_scrollbar()
      .when(Boolean(scrollHandle), el => el.track_scroll(scrollHandle))
      .children(bodyChildren));
}
