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
import { Copy, AlertCircle, ChevronRight } from 'lucide-react'
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

  useEffect(() => {
    const load = async () => {
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
    load()
  }, [])

  useEffect(() => {
    const loadViz = async () => {
      try {
        const data = await fetchGraphVisualization()
        setVisualization(data)
      } catch (err) {
        // Don't show error if visualization file doesn't exist
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

    // Clean up previous network instance
    if (visNetworkRef.current) {
      visNetworkRef.current.destroy()
    }

    try {
      // Handle Neo4j db.schema.visualization() format:
      // nodes: [{name: "NodeName", indexes: [], constraints: []}, ...]
      // relationships: [[startNode, "REL_TYPE", endNode], ...]
      const nodeMap = new Map<string, string>()
      
      // Filter out QueryExample nodes
      const nodes = (visualization.nodes || [])
        .filter((node: any) => {
          const nodeName = node.name || ''
          return nodeName !== 'QueryExample'
        })
        .map((node: any, index: number) => {
          const nodeName = node.name || `Node${index}`
          const nodeId = nodeName // Use name as ID
          nodeMap.set(nodeName, nodeId)
          
          return {
            id: nodeId,
            label: nodeName,
            title: `${nodeName}\nIndexes: ${node.indexes?.length || 0}\nConstraints: ${node.constraints?.length || 0}`,
            color: {
              background: '#e3f2fd',
              border: '#1976d2',
              highlight: { background: '#bbdefb', border: '#0d47a1' },
            },
          }
        })

      const edges: any[] = []
      const relationships = visualization.relationships || []
      
      relationships.forEach((rel: any, index: number) => {
        // Format: [startNode, "REL_TYPE", endNode]
        if (Array.isArray(rel) && rel.length >= 3) {
          const startNode = rel[0]
          const relType = rel[1]
          const endNode = rel[2]
          
          const startName = startNode?.name || String(startNode)
          const endName = endNode?.name || String(endNode)
          
          // Skip relationships involving QueryExample
          if (startName === 'QueryExample' || endName === 'QueryExample') {
            return
          }
          
          const relTypeStr = String(relType)
          
          // Ensure both nodes exist in our node map
          if (!nodeMap.has(startName)) {
            nodeMap.set(startName, startName)
            nodes.push({
              id: startName,
              label: startName,
              title: startName,
              color: {
                background: '#e3f2fd',
                border: '#1976d2',
                highlight: { background: '#bbdefb', border: '#0d47a1' },
              },
            })
          }
          
          if (!nodeMap.has(endName)) {
            nodeMap.set(endName, endName)
            nodes.push({
              id: endName,
              label: endName,
              title: endName,
              color: {
                background: '#e3f2fd',
                border: '#1976d2',
                highlight: { background: '#bbdefb', border: '#0d47a1' },
              },
            })
          }
          
          edges.push({
            id: `edge-${index}`,
            from: startName,
            to: endName,
            label: relTypeStr,
            arrows: 'to',
            color: { color: '#9c27b0', highlight: '#7b1fa2' },
            length: 800, // Doubled edge length for more spacing
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
          font: { size: 28 }, // Doubled from 14
          margin: 40, // Doubled from 20 for bigger nodes
        },
        edges: {
          font: { size: 24, align: 'middle' }, // Doubled from 12
          smooth: { type: 'curvedCW', roundness: 0.2 },
          length: 400, // Doubled from 200
        },
        physics: {
          enabled: true,
          stabilization: { 
            iterations: 200,
            updateInterval: 25,
          },
          barnesHut: {
            gravitationalConstant: -6000, // Doubled repulsion for more space
            centralGravity: 0.1,
            springLength: 800, // Doubled from 400 for double spacing
            springConstant: 0.04,
            damping: 0.09,
            avoidOverlap: 1, // Strong overlap avoidance
          },
        },
        interaction: {
          hover: true,
          tooltipDelay: 100,
          dragNodes: true, // Allow dragging nodes
          dragView: true, // Allow panning
          zoomView: true, // Allow zooming
        },
      }

      visNetworkRef.current = new VisNetwork(networkRef.current, data, options)
      
      // Disable physics after stabilization to keep graph static
      visNetworkRef.current.on('stabilizationEnd', () => {
        if (visNetworkRef.current) {
          visNetworkRef.current.setOptions({ physics: false })
        }
      })
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
      <div className="flex h-full flex-col items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 mb-4"></div>
        <p className="text-gray-600">Loading graph overview...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-red-600">
        <AlertCircle size={32} className="mb-3" />
        <p className="font-medium">{error}</p>
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
        className={`min-w-[220px] rounded-lg border p-4 bg-white shadow-sm text-left transition-all ${
          isActive
            ? 'border-blue-400 ring-2 ring-blue-200'
            : 'border-gray-200 hover:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-200'
        }`}
      >
        <h3 className="text-base font-semibold text-gray-900 mb-1">{node.label}</h3>
        <p className="text-xs text-gray-500">{node.properties?.length ?? 0} properties</p>
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
        className={`min-w-[200px] rounded border px-4 py-3 text-sm transition-all ${
          isActive
            ? 'border-purple-400 bg-white ring-2 ring-purple-200'
            : 'border-gray-200 bg-gray-50 hover:border-purple-400 focus:outline-none focus:ring-2 focus:ring-purple-200'
        } text-gray-800`}
      >
        <span className="font-semibold text-purple-600">{rel.type}</span>
      </button>
    )
  }

  return (
    <div className="flex h-full flex-col p-6 overflow-y-auto space-y-6">
      <div className="flex items-start justify-between gap-6 flex-wrap">
        <div className="max-w-3xl">
          <h1 className="text-3xl font-bold text-gray-900 mb-3">Graph Overview</h1>
          <p className="text-gray-600 leading-relaxed">{info.summary}</p>
        </div>
        <button
          onClick={handleCopy}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-gray-300 text-sm text-gray-700 hover:bg-gray-50"
        >
          <Copy size={16} />
          {copied ? 'Copied!' : 'Copy schema'}
        </button>
      </div>

      <section className="grid grid-cols-1 sm:grid-cols-2 gap-6">
        <div className="rounded-xl border border-blue-100 bg-blue-50 p-4">
          <div className="text-sm font-medium text-blue-800 uppercase tracking-wide mb-1">
            Node Labels
          </div>
          <div className="text-3xl font-bold text-blue-900">{info.nodes.length}</div>
          <p className="text-sm text-blue-700 mt-1">
            Distinct node definitions with properties cached from Neo4j.
          </p>
        </div>
        <div className="rounded-xl border border-purple-100 bg-purple-50 p-4">
          <div className="text-sm font-medium text-purple-800 uppercase tracking-wide mb-1">
            Relationships
          </div>
          <div className="text-3xl font-bold text-purple-900">{info.relationships.length}</div>
          <p className="text-sm text-purple-700 mt-1">
            Directional edges that connect the node labels.
          </p>
        </div>
      </section>

      {visualization && (
        <section className="space-y-4">
          <h2 className="text-xl font-semibold text-gray-900">Schema Visualization</h2>
          {vizError && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-700 text-sm">
              {vizError}
            </div>
          )}
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <div
              ref={networkRef}
              className="w-full"
              style={{ height: '600px', minHeight: '600px' }}
            />
          </div>
        </section>
      )}

      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-gray-900">Node Catalogue</h2>
        </div>
        <div className="flex overflow-x-auto gap-4 pb-2">
          {info.nodes.map(renderNode)}
        </div>
        {selectedNode && (
          <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 space-y-4">
            <div>
              <h3 className="text-lg font-semibold text-blue-900">{selectedNode.label}</h3>
              <p className="text-xs text-blue-700">
                {selectedNode.properties?.length ?? 0} properties •{' '}
                {
                  info.relationships.filter(
                    (rel) =>
                      rel.start === selectedNode.label || rel.end === selectedNode.label
                  ).length
                }{' '}
                relationship touchpoints
              </p>
            </div>
            <div className="bg-white rounded border border-blue-100 p-3 space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-blue-800">
                Description
              </p>
              <p className="text-sm text-gray-700 whitespace-pre-wrap">
                {selectedNode.description || 'No description available.'}
              </p>
            </div>
            <div className="bg-white rounded border border-blue-100 p-3">
              {selectedNode.properties && selectedNode.properties.length > 0 ? (
                <ul className="text-sm text-gray-700 space-y-2">
                  {selectedNode.properties.map((prop, idx) => (
                    <li key={idx} className="flex items-center justify-between">
                      <span className="font-medium text-gray-900">{prop.property}</span>
                      <span className="text-gray-500">{prop.type}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-gray-500">No properties recorded.</p>
              )}
            </div>
          </div>
        )}
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold text-gray-900">Relationship Topology</h2>
        <div className="flex overflow-x-auto gap-3 pb-2">
          {info.relationships.map(renderRelationship)}
        </div>
        {selectedRelationship && (
          <div className="rounded-lg border border-purple-200 bg-purple-50 p-4 space-y-4">
            <div>
              <h3 className="text-lg font-semibold text-purple-900">
                {selectedRelationship.start} —[{selectedRelationship.type}]→ {selectedRelationship.end}
              </h3>
              <p className="text-xs text-purple-700">
                Detailed relationship information from the cached schema.
              </p>
            </div>
            <div className="bg-white rounded border border-purple-100 p-3 space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-purple-800">
                Description
              </p>
              <p className="text-sm text-gray-700 whitespace-pre-wrap">
                {selectedRelationship.description || 'No description available.'}
              </p>
            </div>
            <div className="bg-white rounded border border-purple-100 p-3 text-sm text-gray-700 space-y-1">
              <p>
                <span className="font-semibold text-gray-900">Start Node:</span>{' '}
                {selectedRelationship.start}
              </p>
              <p>
                <span className="font-semibold text-gray-900">Relationship:</span>{' '}
                {selectedRelationship.type}
              </p>
              <p>
                <span className="font-semibold text-gray-900">End Node:</span>{' '}
                {selectedRelationship.end}
              </p>
            </div>
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold text-gray-900">Schema Text</h2>
        <pre className="bg-gray-900 text-gray-100 text-sm rounded-lg p-4 overflow-x-auto">
          {info.schema_text}
        </pre>
      </section>

    </div>
  )
}

