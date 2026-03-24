'use client'

import { useState } from 'react'
import { MessageSquare, Menu, BookOpen, Users, Star, GitBranch, LogOut } from 'lucide-react'

export type MenuOption = 'chat' | 'knowledge-base' | 'favorites' | 'graph-info'

interface SidebarProps {
  activeOption: MenuOption
  onOptionChange: (option: MenuOption) => void
  loggedInUser: string | null
  onLogout: () => void
}

export default function Sidebar({
  activeOption,
  onOptionChange,
  loggedInUser,
  onLogout,
}: SidebarProps) {
  const [isCollapsed, setIsCollapsed] = useState(false)

  const menuOptions = [
    { id: 'chat' as MenuOption, label: 'Chat', icon: MessageSquare },
    { id: 'knowledge-base' as MenuOption, label: 'Knowledge Base', icon: BookOpen },
    { id: 'favorites' as MenuOption, label: 'Favorites', icon: Star },
    { id: 'graph-info' as MenuOption, label: 'Graph Info', icon: GitBranch },
  ]

  return (
    <div className={`bg-gradient-to-b from-gray-900 to-gray-800 text-white transition-all duration-300 ease-in-out ${
      isCollapsed ? 'w-16' : 'w-64'
    } flex flex-col h-screen flex-shrink-0`}>
      {/* Header */}
      <div className="p-4 border-b border-white/10 flex items-center justify-between">
        {!isCollapsed && (
          <h2 className="text-lg font-bold tracking-tight">
            <span className="bg-gradient-to-r from-indigo-400 to-cyan-400 bg-clip-text text-transparent">Graph</span>
            <span className="text-white">RAG</span>
          </h2>
        )}
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="p-2 hover:bg-white/10 rounded-lg transition-colors"
          aria-label="Toggle sidebar"
        >
          <Menu size={20} />
        </button>
      </div>

      {/* Menu Options */}
      <nav className="flex-1 p-3 space-y-1">
        {menuOptions.map((option) => {
          const Icon = option.icon
          const isActive = activeOption === option.id
          
          return (
            <button
              key={option.id}
              onClick={() => onOptionChange(option.id)}
              className={`w-full flex items-center space-x-3 px-3 py-2.5 rounded-xl transition-all duration-200 ${
                isActive
                  ? 'bg-indigo-500/20 text-indigo-300 shadow-lg shadow-indigo-500/10 border border-indigo-500/20'
                  : 'text-gray-400 hover:bg-white/5 hover:text-gray-200 border border-transparent'
              }`}
            >
              <Icon size={18} className={isActive ? 'text-indigo-400' : ''} />
              {!isCollapsed && <span className="text-sm font-medium">{option.label}</span>}
            </button>
          )
        })}
      </nav>

      {/* Footer/User Info */}
      <div className="p-4 border-t border-white/10 space-y-3">
        {!isCollapsed ? (
          <>
            <div className="flex items-center gap-2 text-gray-400 text-xs uppercase tracking-wider">
              <Users size={14} />
              <span>Logged in as</span>
            </div>
            {loggedInUser && (
              <div className="bg-white/5 rounded-lg px-3 py-2 text-sm text-white font-medium border border-white/10">
                {loggedInUser.charAt(0).toUpperCase() + loggedInUser.slice(1)}
              </div>
            )}
            <button
              onClick={onLogout}
              className="w-full flex items-center justify-center gap-2 bg-white/5 hover:bg-white/10 text-gray-300 hover:text-white py-2 px-3 rounded-lg text-sm font-medium transition-all duration-200 border border-white/10"
            >
              <LogOut size={15} />
              <span>Logout</span>
            </button>
            <p className="text-[10px] text-center text-gray-600">
              GraphRAG v1.0.0
            </p>
          </>
        ) : (
          <div className="flex flex-col items-center gap-2 text-[10px] text-gray-600">
            <Users size={16} />
          </div>
        )}
      </div>
    </div>
  )
}
