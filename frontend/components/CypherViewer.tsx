'use client'

import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'

interface CypherViewerProps {
  cypher: string
}

export default function CypherViewer({ cypher }: CypherViewerProps) {
  return (
    <div className="mt-2 max-w-full">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-indigo-500 mb-1.5">Cypher</div>
      <div className="rounded-xl overflow-hidden border border-gray-200 max-w-full shadow-inner bg-slate-900/5">
        <div className="overflow-x-auto">
          <SyntaxHighlighter
            language="cypher"
            style={vscDarkPlus}
            customStyle={{
              margin: 0,
              padding: '12px',
              fontSize: '12px',
              maxWidth: '100%',
              overflow: 'auto',
            }}
          >
            {cypher}
          </SyntaxHighlighter>
        </div>
      </div>
    </div>
  )
}

