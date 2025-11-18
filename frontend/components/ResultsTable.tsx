'use client'

interface ResultsTableProps {
  results: any[]
}

export default function ResultsTable({ results }: ResultsTableProps) {
  if (!results || results.length === 0) {
    return <div className="text-sm text-gray-600">No results found.</div>
  }

  // Get all unique keys from results
  const keys = Array.from(
    new Set(results.flatMap((r) => Object.keys(r)))
  )

  return (
    <div className="mt-2">
      <div className="text-xs font-semibold mb-1">
        Results ({results.length} row{results.length !== 1 ? 's' : ''}):
      </div>
      <div className="overflow-x-auto border border-gray-300 rounded">
        <table className="min-w-full text-xs">
          <thead className="bg-gray-100">
            <tr>
              {keys.map((key) => (
                <th key={key} className="px-3 py-2 text-left font-semibold">
                  {key}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {results.slice(0, 10).map((row, idx) => (
              <tr key={idx} className="border-t border-gray-200">
                {keys.map((key) => (
                  <td key={key} className="px-3 py-2">
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
          <div className="text-xs text-gray-500 px-3 py-2 bg-gray-50">
            Showing first 10 of {results.length} results
          </div>
        )}
      </div>
    </div>
  )
}

