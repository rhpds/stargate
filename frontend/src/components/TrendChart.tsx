import { Chart, ChartArea, ChartAxis } from '@patternfly/react-charts/victory';

interface TrendPoint {
  x: string | number;
  y: number;
  label?: string;
}

interface Props {
  data: TrendPoint[];
  color?: string;
  height?: number;
  width?: number;
  sparkline?: boolean;
  yLabel?: string;
}

export default function TrendChart({
  data,
  color = '#0066CC',
  height = 120,
  width = 400,
  sparkline = false,
  yLabel,
}: Props) {
  if (!data || data.length === 0) return null;

  const padding = sparkline
    ? { top: 4, bottom: 4, left: 4, right: 4 }
    : { top: 10, bottom: 30, left: 40, right: 10 };

  return (
    <div style={{ width, height }}>
      <Chart
        height={height}
        width={width}
        padding={padding}
      >
        {!sparkline && (
          <ChartAxis
            tickCount={4}
            tickFormat={(t: number) => {
              const d = new Date(t);
              return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${d.getMinutes().toString().padStart(2, '0')}`;
            }}
            style={{ tickLabels: { fontSize: 7, angle: -20, textAnchor: 'end' } }}
          />
        )}
        {!sparkline && (
          <ChartAxis
            dependentAxis
            tickCount={3}
            label={yLabel}
            style={{ tickLabels: { fontSize: 8 }, axisLabel: { fontSize: 9, padding: 28 } }}
          />
        )}
        <ChartArea
          data={data}
          style={{ data: { fill: color, fillOpacity: 0.15, stroke: color, strokeWidth: sparkline ? 1.5 : 2 } }}
        />
      </Chart>
    </div>
  );
}
