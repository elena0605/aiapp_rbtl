'use client'

interface ResultsTableProps {
  results: any[]
}

export default function ResultsTable({ results }: ResultsTableProps) {
  if (!results || results.length === 0) {
    return <div className="text-sm text-gray-400 italic">No results found.</div>
  }

  const keys = Array.from(
    new Set(results.flatMap((r) => Object.keys(r)))
  )

  return (
    <div className="mt-2">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-indigo-500 mb-1.5">
        Results ({results.length} row{results.length !== 1 ? 's' : ''})
      </div>
      <div className="overflow-x-auto border border-gray-100 rounded-xl shadow-sm">
        <table className="min-w-full text-xs">
          <thead>
            <tr className="bg-gradient-to-r from-slate-50 to-gray-50 border-b border-gray-100">
              {keys.map((key) => (
                <th key={key} className="px-3.5 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                  {key}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="bg-white">
            {results.slice(0, 10).map((row, idx) => (
              <tr
                key={idx}
                className="border-t border-gray-50 hover:bg-indigo-50/30 transition-colors"
              >
                {keys.map((key) => (
                  <td key={key} className="px-3.5 py-2 text-gray-700">
                    {typeof row[key] === 'object'
                      ? JSON.stringify(row[key])
                      : String(row[key] ?? 'null')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {results.length > 10 && (
          <div className="text-[11px] text-gray-400 px-3.5 py-2 bg-slate-50/80 border-t border-gray-100">
            Showing first 10 of {results.length} results
          </div>
        )}
      </div>
    </div>
  )
}
