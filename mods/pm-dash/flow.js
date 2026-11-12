import { View, div, PathBuilder } from 'gpui-kit';
import { layout } from 'herdr';
import { sampleWire, arcHops } from './model.js';

export function boardVisible(node) {
  if (node?.id === 'pm-stage') return node.active === 'pm-board';
  return (node?.children || []).some(boardVisible);
}

// Retained child: only this script description is invalidated by the flow timer.
export class FlowLayer extends View {
  init(_props, cx) {
    this.phase = 0;
    this.wires = [];
    this.cache = new Map();
    this.overlay = false;
    this.packet = null; this.startPending = false;
    cx.timer.every(110, cx => {
      if (!this.wires.length || (!this.overlay && !boardVisible(layout()))) return;
      this.phase = (this.phase + 2) % 7; // +2 samples = 4px left to right.
      cx.notify();
    });
  }
  update(props) {
    this.overlay = props.overlay;
    this.wires = props.wires;
    const keep = new Set();
    // Geometry is sampled only when coordinates change, never in the tick/render.
    for (const wire of props.geometry) {
      keep.add(wire.id);
      const key = JSON.stringify(wire.points);
      if (this.cache.get(wire.id)?.key !== key) this.cache.set(wire.id, { key, points: sampleWire(wire.points) });
    }
    for (const id of this.cache.keys()) if (!keep.has(id)) this.cache.delete(id);
    this.onComplete = props.onComplete;
    const request = props.packet;
    if (request?.token !== this.packet?.token) {
      this.motion?.cancel();
      this.packet = request ? { ...request, leg: 0, index: 0, duration: 0 } : null;
      this.startPending = Boolean(request);
      if (request) this.prepareLeg();
    } else if (request) {
      Object.assign(this.packet, { color: request.color, opacity: request.opacity, background: request.background });
      // Reflow only when this leg's geometry changed; hover/theme updates must
      // not restart its timing or reset the native transition.
      const geometry = this.cache.get(this.packet.routes[this.packet.leg]);
      if (!this.packet.complete && geometry !== this.packet.geometry) {
        const progress = this.packet.index;
        this.prepareLeg();
        this.packet.index = Math.min(progress, this.packet.hops.length);
        this.packet.point = this.packet.hops[this.packet.index - 1]?.to || this.packet.point;
      }
    }
  }
  prepareLeg() {
    const p = this.packet;
    p.geometry = this.cache.get(p.routes[p.leg]);
    p.hops = p.geometry ? arcHops(p.geometry.points, p.reverse) : [];
    p.index = 0; p.duration = 0;
    const pts = p.geometry?.points;
    p.point = p.hops[0]?.from || (pts ? (p.reverse ? pts.at(-1) : pts[0]) : null);
  }
  advance(cx, token) {
    const p = this.packet;
    if (!p || p.token !== token || p.complete) return;
    const hop = p.hops[p.index];
    if (hop) {
      p.index++; p.point = hop.to; p.duration = hop.duration;
      cx.notify();
      this.motion = cx.timer.after(hop.duration, cx => this.advance(cx, token));
    } else if (p.leg + 1 < p.routes.length) {
      p.leg++; this.prepareLeg();
      cx.notify();
      // New element identity at each leg: mount at its actual start first.
      this.motion = cx.timer.after(30, cx => this.advance(cx, token));
    } else {
      p.complete = true;
      this.onComplete?.(token); // Only completion wakes the parent.
    }
  }
  render(cx) {
    const layer = div().absolute().left(0).top(0).size_full();
    for (const wire of this.wires) {
      const pts = this.cache.get(wire.id).points, b = PathBuilder.stroke(2.2);
      // One path per wire; each subpath is 6px on, followed by 8px off.
      for (let i = this.phase - 7; i < pts.length - 1; i += 7) {
        const a = Math.max(0, i), z = Math.min(pts.length - 1, i + 3);
        if (z <= a) continue;
        b.move_to(pts[a].x, pts[a].y);
        for (let j = a + 1; j <= z; j++) b.line_to(pts[j].x, pts[j].y);
      }
      layer.child(window.paint_path(b.build(), wire.color).id(`flow:${wire.id}`)
        .absolute().left(0).top(0).size_full().opacity(wire.opacity).transition('opacity', 160));
    }
    const p = this.packet;
    if (p?.point) {
      layer.child(div().id(`packet:${p.token}:${p.leg}`).absolute().left(p.point.x - 5).top(p.point.y - 5)
        .w(10).h(10).rounded(5).border(2).border_color(p.color).bg(p.reverse ? p.background : p.color)
        .opacity(p.opacity).transition('opacity', 160)
        .transition('left', { duration: p.duration, easing: 'linear' })
        .transition('top', { duration: p.duration, easing: 'linear' }));
    }
    if (this.startPending && p) {
      this.startPending = false;
      this.motion = cx.timer.after(30, cx => this.advance(cx, p.token));
    }
    return layer;
  }
}
