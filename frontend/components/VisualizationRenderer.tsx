'use client'

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
  ResponsiveContainer,
} from 'recharts'

const COLORS = [
  '#6366f1', '#0ea5e9', '#14b8a6', '#f59e0b', '#f43f5e',
  '#8b5cf6', '#06b6d4', '#84cc16', '#fb923c', '#e879f9',
]

export interface VisualizationData {
  chart_type: 'bar' | 'horizontal_bar' | 'pie' | 'line' | 'table' | 'number'
  title: string
  description?: string
  data: any
  axes?: { x?: string | null; y?: string | null }
  summary?: string
}

interface VisualizationRendererProps {
  visualization: VisualizationData
}

function buildRechartsData(labels: string[], datasets: { label: string; data: number[] }[]) {
  return labels.map((label, i) => {
    const point: Record<string, any> = { name: label }
    datasets.forEach((ds) => {
      point[ds.label] = ds.data[i] ?? 0
    })
    return point
  })
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-gray-900 text-white text-xs rounded-lg px-3 py-2 shadow-xl border border-gray-700">
      <p className="font-medium mb-1">{label}</p>
      {payload.map((entry: any, i: number) => (
        <p key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full inline-block" style={{ backgroundColor: entry.color }} />
          <span className="text-gray-300">{entry.name}:</span>
          <span className="font-semibold">{typeof entry.value === 'number' ? entry.value.toLocaleString() : entry.value}</span>
        </p>
      ))}
    </div>
  )
}

function BarChartView({ visualization }: { visualization: VisualizationData }) {
  const { labels = [], datasets = [] } = visualization.data || {}
  if (!labels.length || !datasets.length) return <EmptyState />
  const chartData = buildRechartsData(labels, datasets)

  return (
    <ResponsiveContainer width="100%" height={320}>
      <BarChart data={chartData} margin={{ top: 10, right: 20, bottom: 5, left: 10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
        <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#6b7280' }} interval={0} angle={-30} textAnchor="end" height={70} axisLine={{ stroke: '#d1d5db' }} tickLine={false} />
        <YAxis tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(99, 102, 241, 0.08)' }} />
        {datasets.length > 1 && <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12 }} />}
        {datasets.map((ds: any, i: number) => (
          <Bar key={ds.label} dataKey={ds.label} fill={COLORS[i % COLORS.length]} radius={[4, 4, 0, 0]} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

function HorizontalBarChartView({ visualization }: { visualization: VisualizationData }) {
  const { labels = [], datasets = [] } = visualization.data || {}
  if (!labels.length || !datasets.length) return <EmptyState />
  const chartData = buildRechartsData(labels, datasets)

  return (
    <ResponsiveContainer width="100%" height={Math.max(320, labels.length * 36)}>
      <BarChart data={chartData} layout="vertical" margin={{ top: 10, right: 20, bottom: 5, left: 100 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" horizontal={false} />
        <XAxis type="number" tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={{ stroke: '#d1d5db' }} tickLine={false} />
        <YAxis dataKey="name" type="category" tick={{ fontSize: 11, fill: '#374151' }} width={95} axisLine={false} tickLine={false} />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(99, 102, 241, 0.08)' }} />
        {datasets.length > 1 && <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12 }} />}
        {datasets.map((ds: any, i: number) => (
          <Bar key={ds.label} dataKey={ds.label} fill={COLORS[i % COLORS.length]} radius={[0, 4, 4, 0]} barSize={20} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

function PieChartView({ visualization }: { visualization: VisualizationData }) {
  const { labels = [], datasets = [] } = visualization.data || {}
  if (!labels.length || !datasets.length) return <EmptyState />

  const pieData = labels.map((label: string, i: number) => ({
    name: label,
    value: datasets[0]?.data?.[i] ?? 0,
  }))

  return (
    <ResponsiveContainer width="100%" height={340}>
      <PieChart>
        <Pie
          data={pieData}
          cx="50%"
          cy="50%"
          labelLine={{ stroke: '#9ca3af', strokeWidth: 1 }}
          label={({ name, percent }: { name?: string; percent?: number }) => `${name ?? ''} (${((percent ?? 0) * 100).toFixed(0)}%)`}
          outerRadius={115}
          innerRadius={45}
          dataKey="value"
          paddingAngle={2}
          stroke="none"
        >
          {pieData.map((_: any, i: number) => (
            <Cell key={`cell-${i}`} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip content={<CustomTooltip />} />
      </PieChart>
    </ResponsiveContainer>
  )
}

function LineChartView({ visualization }: { visualization: VisualizationData }) {
  const { labels = [], datasets = [] } = visualization.data || {}
  if (!labels.length || !datasets.length) return <EmptyState />
  const chartData = buildRechartsData(labels, datasets)

  return (
    <ResponsiveContainer width="100%" height={320}>
      <LineChart data={chartData} margin={{ top: 10, right: 20, bottom: 5, left: 10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
        <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={{ stroke: '#d1d5db' }} tickLine={false} />
        <YAxis tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} />
        <Tooltip content={<CustomTooltip />} />
        {datasets.length > 1 && <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12 }} />}
        {datasets.map((ds: any, i: number) => (
          <Line
            key={ds.label}
            type="monotone"
            dataKey={ds.label}
            stroke={COLORS[i % COLORS.length]}
            strokeWidth={2.5}
            dot={{ r: 4, fill: COLORS[i % COLORS.length], strokeWidth: 0 }}
            activeDot={{ r: 6, strokeWidth: 2, stroke: '#fff' }}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

function NumberView({ visualization }: { visualization: VisualizationData }) {
  const { value, label } = visualization.data || {}
  return (
    <div className="flex flex-col items-center py-8">
      <div className="text-5xl font-bold bg-gradient-to-r from-indigo-500 to-cyan-500 bg-clip-text text-transparent">
        {typeof value === 'number' ? value.toLocaleString() : value}
      </div>
      {label && <div className="text-sm text-gray-500 mt-3 font-medium">{label}</div>}
    </div>
  )
}

function TableView({ visualization }: { visualization: VisualizationData }) {
  const { columns = [], rows = [] } = visualization.data || {}
  if (!columns.length) return <EmptyState />

  return (
    <div className="overflow-x-auto max-h-72 rounded-lg">
      <table className="min-w-full text-xs">
        <thead className="sticky top-0">
          <tr className="bg-gray-50">
            {columns.map((col: string, i: number) => (
              <th key={i} className="px-4 py-2.5 text-left font-semibold text-gray-600 border-b-2 border-gray-200 uppercase tracking-wider text-[10px]">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {rows.slice(0, 50).map((row: any[], ri: number) => (
            <tr key={ri} className="hover:bg-indigo-50/50 transition-colors">
              {row.map((cell: any, ci: number) => (
                <td key={ci} className="px-4 py-2 text-gray-700">
                  {cell != null ? String(cell) : ''}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="text-sm text-gray-400 py-8 text-center">
      <div className="text-3xl mb-2">📊</div>
      No data available for visualization.
    </div>
  )
}

export default function VisualizationRenderer({ visualization }: VisualizationRendererProps) {
  const chartRenderers: Record<string, React.FC<{ visualization: VisualizationData }>> = {
    bar: BarChartView,
    horizontal_bar: HorizontalBarChartView,
    pie: PieChartView,
    line: LineChartView,
    number: NumberView,
    table: TableView,
  }

  const ChartComponent = chartRenderers[visualization.chart_type] || TableView

  return (
    <div className="mt-3 bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
      <div className="px-5 py-3 border-b border-gray-100">
        <div className="font-semibold text-sm text-gray-800">{visualization.title}</div>
        {visualization.description && (
          <div className="text-xs text-gray-500 mt-0.5">{visualization.description}</div>
        )}
      </div>
      <div className="p-4">
        <ChartComponent visualization={visualization} />
      </div>
      {visualization.summary && (
        <div className="px-5 py-3 bg-indigo-50/60 border-t border-indigo-100 text-xs text-indigo-700 leading-relaxed">
          {visualization.summary}
        </div>
      )}
    </div>
  )
}
