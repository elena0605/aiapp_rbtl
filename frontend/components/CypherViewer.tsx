'use client'

import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'

interface CypherViewerProps {
  cypher: string
}

export default function CypherViewer({ cypher }: CypherViewerProps) {
  return (
    <div className="mt-2 max-w-full">
      <div className="text-xs font-semibold mb-1">Generated Cypher:</div>
      <div className="rounded overflow-hidden border border-gray-300 max-w-full">
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

