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
  '#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6',
  '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1',
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

function BarChartView({ visualization }: { visualization: VisualizationData }) {
  const { labels = [], datasets = [] } = visualization.data || {}
  if (!labels.length || !datasets.length) return <EmptyState />
  const chartData = buildRechartsData(labels, datasets)

  return (
    <ResponsiveContainer width="100%" height={320}>
      <BarChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} angle={-30} textAnchor="end" height={70} />
        <YAxis tick={{ fontSize: 11 }} />
        <Tooltip />
        {datasets.length > 1 && <Legend />}
        {datasets.map((ds: any, i: number) => (
          <Bar key={ds.label} dataKey={ds.label} fill={COLORS[i % COLORS.length]} />
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
    <ResponsiveContainer width="100%" height={Math.max(320, labels.length * 32)}>
      <BarChart data={chartData} layout="vertical" margin={{ top: 5, right: 20, bottom: 5, left: 80 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis type="number" tick={{ fontSize: 11 }} />
        <YAxis dataKey="name" type="category" tick={{ fontSize: 11 }} width={75} />
        <Tooltip />
        {datasets.length > 1 && <Legend />}
        {datasets.map((ds: any, i: number) => (
          <Bar key={ds.label} dataKey={ds.label} fill={COLORS[i % COLORS.length]} />
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
    <ResponsiveContainer width="100%" height={320}>
      <PieChart>
        <Pie
          data={pieData}
          cx="50%"
          cy="50%"
          labelLine
          label={({ name, percent }: { name?: string; percent?: number }) => `${name ?? ''} (${((percent ?? 0) * 100).toFixed(0)}%)`}
          outerRadius={110}
          dataKey="value"
        >
          {pieData.map((_: any, i: number) => (
            <Cell key={`cell-${i}`} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip />
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
      <LineChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="name" tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} />
        <Tooltip />
        {datasets.length > 1 && <Legend />}
        {datasets.map((ds: any, i: number) => (
          <Line
            key={ds.label}
            type="monotone"
            dataKey={ds.label}
            stroke={COLORS[i % COLORS.length]}
            strokeWidth={2}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

function NumberView({ visualization }: { visualization: VisualizationData }) {
  const { value, label } = visualization.data || {}
  return (
    <div className="flex flex-col items-center py-6">
      <div className="text-4xl font-bold text-blue-600">
        {typeof value === 'number' ? value.toLocaleString() : value}
      </div>
      {label && <div className="text-sm text-gray-500 mt-2">{label}</div>}
    </div>
  )
}

function TableView({ visualization }: { visualization: VisualizationData }) {
  const { columns = [], rows = [] } = visualization.data || {}
  if (!columns.length) return <EmptyState />

  return (
    <div className="overflow-x-auto max-h-64">
      <table className="min-w-full text-xs border-collapse">
        <thead>
          <tr className="bg-gray-100">
            {columns.map((col: string, i: number) => (
              <th key={i} className="px-3 py-1.5 text-left font-semibold border-b border-gray-200">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 50).map((row: any[], ri: number) => (
            <tr key={ri} className={ri % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
              {row.map((cell: any, ci: number) => (
                <td key={ci} className="px-3 py-1 border-b border-gray-100">
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
  return <div className="text-sm text-gray-400 py-4 text-center">No data available for visualization.</div>
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
    <div className="mt-3 bg-white border border-gray-200 rounded-lg overflow-hidden">
      <div className="px-4 py-2 bg-gray-50 border-b border-gray-200">
        <div className="font-semibold text-sm text-gray-800">{visualization.title}</div>
        {visualization.description && (
          <div className="text-xs text-gray-500 mt-0.5">{visualization.description}</div>
        )}
      </div>
      <div className="p-4">
        <ChartComponent visualization={visualization} />
      </div>
      {visualization.summary && (
        <div className="px-4 py-2 bg-blue-50 border-t border-blue-100 text-xs text-blue-800">
          {visualization.summary}
        </div>
      )}
    </div>
  )
}
