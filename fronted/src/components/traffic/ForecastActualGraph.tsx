import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts';
import type { ForecastActual } from '@/types/traffic';
import { strings } from '@/strings';

export function ForecastActualGraph({ rows }: { rows: ForecastActual[] }) {
  const data = [...rows].sort((a, b) => a.target_timestamp.localeCompare(b.target_timestamp)).map(row => ({
    time: new Date(row.target_timestamp).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }),
    predicted: row.predicted_congestion_percent,
    observed: row.actual_congestion_percent,
  }));

  return <div className="h-72 w-full" role="img" aria-label="Line chart comparing predicted and observed congestion for a selected corridor">
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 8 }}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
        <XAxis dataKey="time" minTickGap={30} tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }} />
        <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }} />
        <Tooltip formatter={(value, name) => [`${Number(value).toFixed(1)}%`, name]} />
        <Legend />
        <Line type="monotone" dataKey="predicted" name={strings.verification.predicted} stroke="#2563eb" strokeDasharray="6 4" strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
        <Line type="monotone" dataKey="observed" name={strings.verification.observed} stroke="#059669" strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
      </LineChart>
    </ResponsiveContainer>
  </div>;
}
