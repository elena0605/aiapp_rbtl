'use client'

import { useEffect, useState, useRef } from 'react'
import {
  fetchGraphInfo,
  fetchGraphVisualization,
  GraphInfoResponse,
  GraphNodeInfo,
  GraphRelationshipInfo,
  GraphVisualizationResponse,
} from '@/lib/api'
import { Copy, Check, AlertCircle, RefreshCw, Database, GitBranch } from 'lucide-react'
import { Network as VisNetwork } from 'vis-network'
import 'vis-network/styles/vis-network.min.css'

export default function GraphInfo() {
  const [info, setInfo] = useState<GraphInfoResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [selectedNode, setSelectedNode] = useState<GraphNodeInfo | null>(null)
  const [selectedRelationship, setSelectedRelationship] =
    useState<GraphRelationshipInfo | null>(null)
  const [visualization, setVisualization] = useState<GraphVisualizationResponse | null>(null)
  const [vizError, setVizError] = useState<string | null>(null)
  const networkRef = useRef<HTMLDivElement>(null)
  const visNetworkRef = useRef<VisNetwork | null>(null)

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchGraphInfo()
      setInfo(data)
    } catch (err) {
      setError(
        `Unable to load graph info${
          err instanceof Error ? `: ${err.message}` : ''
        }`
      )
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  useEffect(() => {
    const loadViz = async () => {
      try {
        const data = await fetchGraphVisualization()
        setVisualization(data)
      } catch (err) {
        if (err instanceof Error && err.message.includes('404')) {
          setVizError(null)
        } else {
          setVizError(
            `Unable to load visualization${
              err instanceof Error ? `: ${err.message}` : ''
            }`
          )
        }
      }
    }
    loadViz()
  }, [])

  useEffect(() => {
    if (!visualization || !networkRef.current) return

    if (visNetworkRef.current) {
      visNetworkRef.current.destroy()
    }

    try {
      const nodeMap = new Map<string, string>()

      const nodes = (visualization.nodes || [])
        .filter((node: any) => {
          const nodeName = node.name || ''
          return nodeName !== 'QueryExample'
        })
        .map((node: any, index: number) => {
          const nodeName = node.name || `Node${index}`
          const nodeId = nodeName
          nodeMap.set(nodeName, nodeId)

          return {
            id: nodeId,
            label: nodeName,
            title: `${nodeName}\nIndexes: ${node.indexes?.length || 0}\nConstraints: ${node.constraints?.length || 0}`,
            color: {
              background: '#eef2ff',
              border: '#6366f1',
              highlight: { background: '#c7d2fe', border: '#4338ca' },
            },
            font: { color: '#1e1b4b' },
          }
        })

      const edges: any[] = []
      const relationships = visualization.relationships || []

      relationships.forEach((rel: any, index: number) => {
        if (Array.isArray(rel) && rel.length >= 3) {
          const startNode = rel[0]
          const relType = rel[1]
          const endNode = rel[2]

          const startName = startNode?.name || String(startNode)
          const endName = endNode?.name || String(endNode)

          if (startName === 'QueryExample' || endName === 'QueryExample') {
            return
          }

          const relTypeStr = String(relType)

          if (!nodeMap.has(startName)) {
            nodeMap.set(startName, startName)
            nodes.push({
              id: startName,
              label: startName,
              title: startName,
              color: {
                background: '#eef2ff',
                border: '#6366f1',
                highlight: { background: '#c7d2fe', border: '#4338ca' },
              },
              font: { color: '#1e1b4b' },
            })
          }

          if (!nodeMap.has(endName)) {
            nodeMap.set(endName, endName)
            nodes.push({
              id: endName,
              label: endName,
              title: endName,
              color: {
                background: '#eef2ff',
                border: '#6366f1',
                highlight: { background: '#c7d2fe', border: '#4338ca' },
              },
              font: { color: '#1e1b4b' },
            })
          }

          edges.push({
            id: `edge-${index}`,
            from: startName,
            to: endName,
            label: relTypeStr,
            arrows: 'to',
            color: { color: '#8b5cf6', highlight: '#7c3aed' },
            font: { color: '#5b21b6', strokeWidth: 0 },
            length: 800,
          })
        }
      })

      if (nodes.length === 0 && edges.length === 0) {
        return
      }

      const data = { nodes, edges }
      const options = {
        nodes: {
          shape: 'box',
          font: { size: 28 },
          margin: { top: 40, right: 40, bottom: 40, left: 40 },
          borderWidth: 2,
          borderWidthSelected: 3,
          shadow: {
            enabled: true,
            color: 'rgba(99, 102, 241, 0.15)',
            size: 8,
            x: 0,
            y: 2,
          },
        },
        edges: {
          font: { size: 24, align: 'middle' as const },
          smooth: { enabled: true, type: 'curvedCW' as const, roundness: 0.2 },
          length: 400,
          width: 2,
        },
        physics: {
          enabled: true,
          stabilization: {
            iterations: 200,
            updateInterval: 25,
          },
          barnesHut: {
            gravitationalConstant: -6000,
            centralGravity: 0.1,
            springLength: 800,
            springConstant: 0.04,
            damping: 0.09,
            avoidOverlap: 1,
          },
        },
        interaction: {
          hover: true,
          tooltipDelay: 100,
          dragNodes: true,
          dragView: true,
          zoomView: true,
        },
      }

      const container = networkRef.current
      visNetworkRef.current = new VisNetwork(container, data, options)

      ;(visNetworkRef.current as any).on('stabilizationEnd', () => {
        if (visNetworkRef.current) {
          visNetworkRef.current.setOptions({ physics: false })
          visNetworkRef.current.fit({ animation: { duration: 400, easingFunction: 'easeInOutQuad' } })
        }
      })

      // Redraw after a short delay to handle cases where the container
      // isn't fully laid out yet (e.g. inside a scrollable flex container)
      const redrawTimer = setTimeout(() => {
        if (visNetworkRef.current) {
          visNetworkRef.current.redraw()
          visNetworkRef.current.fit()
        }
      }, 200)

      return () => {
        clearTimeout(redrawTimer)
        if (visNetworkRef.current) {
          visNetworkRef.current.destroy()
          visNetworkRef.current = null
        }
      }
    } catch (err) {
      console.error('Error rendering visualization:', err)
      setVizError(`Failed to render visualization: ${err instanceof Error ? err.message : String(err)}`)
    }

    return () => {
      if (visNetworkRef.current) {
        visNetworkRef.current.destroy()
        visNetworkRef.current = null
      }
    }
  }, [visualization])

  const handleCopy = async () => {
    if (!info) return
    await navigator.clipboard.writeText(info.schema_text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  if (loading) {
    return (
      <div className="flex h-full flex-col items-center justify-center bg-slate-50/50">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-indigo-200 border-t-indigo-500 mb-4"></div>
        <p className="text-gray-500 text-sm">Loading graph overview&hellip;</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center bg-slate-50/50 px-6">
        <div className="bg-rose-50 border border-rose-100 rounded-2xl p-6 max-w-md text-center">
          <div className="w-12 h-12 rounded-xl bg-rose-100 flex items-center justify-center mx-auto mb-3">
            <AlertCircle size={22} className="text-rose-500" />
          </div>
          <p className="text-rose-700 text-sm font-medium mb-4">{error}</p>
          <button
            onClick={loadData}
            className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-500 text-white text-sm font-medium rounded-xl hover:bg-indigo-600 transition-colors shadow-sm"
          >
            <RefreshCw size={15} />
            Retry
          </button>
        </div>
      </div>
    )
  }

  if (!info) {
    return null
  }

  const renderNode = (node: GraphNodeInfo) => {
    const isActive = selectedNode?.label === node.label
    return (
      <button
        key={node.label}
        onClick={() => setSelectedNode(isActive ? null : node)}
        className={`min-w-[220px] rounded-2xl border p-4 bg-white shadow-sm text-left transition-all duration-200 ${
          isActive
            ? 'border-indigo-400 ring-2 ring-indigo-100 shadow-md shadow-indigo-100/50'
            : 'border-gray-100 hover:border-indigo-200 hover:shadow-md hover:shadow-indigo-50'
        }`}
      >
        <h3 className="text-sm font-semibold text-gray-900 mb-1">{node.label}</h3>
        <p className="text-xs text-gray-400">{node.properties?.length ?? 0} properties</p>
      </button>
    )
  }

  const renderRelationship = (rel: GraphRelationshipInfo, idx: number) => {
    const isActive =
      selectedRelationship?.start === rel.start &&
      selectedRelationship?.type === rel.type &&
      selectedRelationship?.end === rel.end

    return (
      <button
        key={`${rel.start}-${rel.type}-${rel.end}-${idx}`}
        onClick={() => setSelectedRelationship(isActive ? null : rel)}
        className={`min-w-[200px] rounded-2xl border px-4 py-3 text-sm transition-all duration-200 ${
          isActive
            ? 'border-violet-400 bg-white ring-2 ring-violet-100 shadow-md shadow-violet-100/50'
            : 'border-gray-100 bg-white hover:border-violet-200 hover:shadow-md hover:shadow-violet-50'
        }`}
      >
        <span className="font-semibold text-violet-600">{rel.type}</span>
      </button>
    )
  }

  return (
    <div className="flex h-full flex-col p-6 md:p-8 overflow-y-auto space-y-8 bg-slate-50/30">
      {/* Header */}
      <div className="flex items-start justify-between gap-6 flex-wrap flex-shrink-0">
        <div className="max-w-3xl">
          <p className="text-xs font-semibold uppercase tracking-wider text-indigo-500 mb-1">Schema</p>
          <h1 className="text-3xl font-bold text-gray-900 tracking-tight mb-2">Graph Overview</h1>
          <p className="text-gray-500 leading-relaxed">{info.summary}</p>
        </div>
        <button
          onClick={handleCopy}
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-gray-200 bg-white text-sm font-medium text-gray-600 hover:bg-gray-50 hover:border-gray-300 transition-all shadow-sm shrink-0"
        >
          {copied ? <Check size={16} className="text-emerald-500" /> : <Copy size={16} />}
          {copied ? 'Copied!' : 'Copy schema'}
        </button>
      </div>

      {/* Stats */}
      <section className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        <div className="rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50 to-blue-50/50 p-5 shadow-sm">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-8 h-8 rounded-lg bg-indigo-100 flex items-center justify-center">
              <Database size={16} className="text-indigo-600" />
            </div>
            <span className="text-[10px] font-semibold uppercase tracking-wider text-indigo-600">Node Labels</span>
          </div>
          <div className="text-3xl font-bold text-gray-900 mb-1">{info.nodes.length}</div>
          <p className="text-xs text-indigo-500/80">
            Distinct node definitions with properties cached from Neo4j.
          </p>
        </div>
        <div className="rounded-2xl border border-violet-100 bg-gradient-to-br from-violet-50 to-purple-50/50 p-5 shadow-sm">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-8 h-8 rounded-lg bg-violet-100 flex items-center justify-center">
              <GitBranch size={16} className="text-violet-600" />
            </div>
            <span className="text-[10px] font-semibold uppercase tracking-wider text-violet-600">Relationships</span>
          </div>
          <div className="text-3xl font-bold text-gray-900 mb-1">{info.relationships.length}</div>
          <p className="text-xs text-violet-500/80">
            Directional edges that connect the node labels.
          </p>
        </div>
      </section>

      {/* Visualization */}
      {visualization && (
        <section className="space-y-4">
          <h2 className="text-lg font-semibold text-gray-900 tracking-tight">Schema Visualization</h2>
          {vizError && (
            <div className="rounded-xl border border-rose-100 bg-rose-50 p-4 text-rose-700 text-sm">
              {vizError}
            </div>
          )}
          <div className="rounded-2xl border border-gray-100 bg-white p-2 shadow-sm">
            <div
              ref={networkRef}
              className="w-full rounded-xl"
              style={{ height: '600px', minHeight: '600px' }}
            />
          </div>
        </section>
      )}

      {/* Node Catalogue */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold text-gray-900 tracking-tight">Node Catalogue</h2>
        <div className="flex overflow-x-auto gap-3 pb-2">
          {info.nodes.map(renderNode)}
        </div>
        {selectedNode && (
          <div className="rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50/80 to-white p-5 space-y-4 shadow-sm">
            <div>
              <h3 className="text-base font-semibold text-gray-900">{selectedNode.label}</h3>
              <p className="text-xs text-indigo-500 mt-0.5">
                {selectedNode.properties?.length ?? 0} properties &middot;{' '}
                {
                  info.relationships.filter(
                    (rel) =>
                      rel.start === selectedNode.label || rel.end === selectedNode.label
                  ).length
                }{' '}
                relationship touchpoints
              </p>
            </div>
            <div className="bg-white rounded-xl border border-indigo-100/60 p-4 space-y-2">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-indigo-500">
                Description
              </p>
              <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
                {selectedNode.description || 'No description available.'}
              </p>
            </div>
            <div className="bg-white rounded-xl border border-indigo-100/60 p-4">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-indigo-500 mb-3">
                Properties
              </p>
              {selectedNode.properties && selectedNode.properties.length > 0 ? (
                <ul className="text-sm text-gray-700 space-y-2">
                  {selectedNode.properties.map((prop, idx) => (
                    <li key={idx} className="flex items-center justify-between py-1 border-b border-gray-50 last:border-0">
                      <span className="font-medium text-gray-900">{prop.property}</span>
                      <span className="text-xs text-gray-400 bg-gray-50 px-2 py-0.5 rounded-md">{prop.type}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-gray-400">No properties recorded.</p>
              )}
            </div>
          </div>
        )}
      </section>

      {/* Relationship Topology */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold text-gray-900 tracking-tight">Relationship Topology</h2>
        <div className="flex overflow-x-auto gap-3 pb-2">
          {info.relationships.map(renderRelationship)}
        </div>
        {selectedRelationship && (
          <div className="rounded-2xl border border-violet-100 bg-gradient-to-br from-violet-50/80 to-white p-5 space-y-4 shadow-sm">
            <div>
              <h3 className="text-base font-semibold text-gray-900">
                {selectedRelationship.start}{' '}
                <span className="text-violet-500">&mdash;[{selectedRelationship.type}]&rarr;</span>{' '}
                {selectedRelationship.end}
              </h3>
              <p className="text-xs text-violet-500 mt-0.5">
                Relationship details from the cached schema.
              </p>
            </div>
            <div className="bg-white rounded-xl border border-violet-100/60 p-4 space-y-2">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-violet-500">
                Description
              </p>
              <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
                {selectedRelationship.description || 'No description available.'}
              </p>
            </div>
            <div className="bg-white rounded-xl border border-violet-100/60 p-4 text-sm text-gray-700 space-y-2">
              <div className="flex items-center justify-between py-1 border-b border-gray-50">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Start Node</span>
                <span className="font-medium text-gray-900">{selectedRelationship.start}</span>
              </div>
              <div className="flex items-center justify-between py-1 border-b border-gray-50">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Relationship</span>
                <span className="font-medium text-violet-600">{selectedRelationship.type}</span>
              </div>
              <div className="flex items-center justify-between py-1">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">End Node</span>
                <span className="font-medium text-gray-900">{selectedRelationship.end}</span>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Schema Text */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-gray-900 tracking-tight">Schema Text</h2>
        <pre className="bg-slate-900 text-slate-100 text-xs font-mono rounded-xl p-5 overflow-x-auto shadow-inner leading-relaxed">
          {info.schema_text}
        </pre>
      </section>
    </div>
  )
}
