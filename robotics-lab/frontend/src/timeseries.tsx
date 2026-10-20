import { useEffect, useRef, useState } from "react";

const COLORS = ["#247b69", "#cd603f", "#3f79b5"];

export function TimeSeries({ times, title, unit, series }: {
  times: number[]; title: string; unit: string;
  series: { name: string; values: (number | null | undefined)[] }[];
}) {
  const finite = series.flatMap(s => s.values.filter((v): v is number => v != null && Number.isFinite(v)));
  const ready = times.length >= 2 && finite.length > 0;
  const svg = useRef<SVGSVGElement | null>(null);
  const [width, setWidth] = useState(640);
  useEffect(() => {
    if (!ready || !svg.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240,Math.round(entry.contentRect.width))));
    observer.observe(svg.current);
    return () => observer.disconnect();
  },[ready]);
  if (!ready) return <div className="empty-chart">{title}：运行后显示曲线。</div>;
  const low = Math.min(...finite), high = Math.max(...finite);
  const padding = Math.max((high-low)*.08, .001), min = low-padding, span = high-low+2*padding;
  const start = times[0], elapsed = Math.max(.001, times.at(-1)!-start);
  return <div className="chart time-series">
    <div className="chart-caption"><span>{title} / {unit}</span><span className="series-legend">
      {series.map((s,i) => <span key={s.name} style={{color: COLORS[i % COLORS.length]}}>{s.name}</span>)}
    </span></div>
    <svg ref={svg} viewBox={`0 0 ${width} 170`} role="img" aria-label={`${title} / ${unit}`}>
      {[30,85,140].map(y => <path key={y} d={`M58 ${y}H${width-15}`} className="chart-grid" />)}
      {series.map((s,k) => {
        let connected = false;
        const path = s.values.map((v,i) => {
          if (v == null || !Number.isFinite(v)) { connected = false; return ""; }
          const segment = `${connected ? "L" : "M"}${(58+(times[i]-start)/elapsed*(width-73)).toFixed(2)},${(140-(v-min)/span*110).toFixed(2)}`;
          connected = true;
          return segment;
        }).join(" ");
        return <path key={s.name} d={path} fill="none" stroke={COLORS[k % COLORS.length]} strokeWidth="2" />;
      })}
      <text x="3" y="30">{(min+span).toFixed(3)}</text><text x="3" y="140">{min.toFixed(3)}</text>
      <text x="58" y="163">{start.toFixed(1)} s</text><text x={width-15} y="163" textAnchor="end">{times.at(-1)!.toFixed(1)} s</text>
    </svg>
  </div>;
}
