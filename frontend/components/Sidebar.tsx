'use client'

import { useState } from 'react'
import { MessageSquare, Menu, BookOpen } from 'lucide-react'

export type MenuOption = 'chat' | 'knowledge-base' | 'settings' | 'history'

interface SidebarProps {
  activeOption: MenuOption
  onOptionChange: (option: MenuOption) => void
}

export default function Sidebar({ activeOption, onOptionChange }: SidebarProps) {
  const [isCollapsed, setIsCollapsed] = useState(false)

  const menuOptions = [
    { id: 'chat' as MenuOption, label: 'Chat', icon: MessageSquare },
    { id: 'knowledge-base' as MenuOption, label: 'Knowledge Base', icon: BookOpen },
    // More options can be added here in the future
    // { id: 'settings' as MenuOption, label: 'Settings', icon: Settings },
    // { id: 'history' as MenuOption, label: 'History', icon: History },
  ]

  return (
    <div className={`bg-gray-800 text-white transition-all duration-300 ${
      isCollapsed ? 'w-16' : 'w-64'
    } flex flex-col h-screen border-r border-gray-700 flex-shrink-0`}>
      {/* Header */}
      <div className="p-4 border-b border-gray-700 flex items-center justify-between">
        {!isCollapsed && (
          <h2 className="text-lg font-semibold">GraphRAG</h2>
        )}
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="p-2 hover:bg-gray-700 rounded transition-colors"
          aria-label="Toggle sidebar"
        >
          <Menu size={20} />
        </button>
      </div>

      {/* Menu Options */}
      <nav className="flex-1 p-4 space-y-2">
        {menuOptions.map((option) => {
          const Icon = option.icon
          const isActive = activeOption === option.id
          
          return (
            <button
              key={option.id}
              onClick={() => onOptionChange(option.id)}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg transition-colors ${
                isActive
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-300 hover:bg-gray-700 hover:text-white'
              }`}
            >
              <Icon size={20} />
              {!isCollapsed && <span>{option.label}</span>}
            </button>
          )
        })}
      </nav>

      {/* Footer */}
      {!isCollapsed && (
        <div className="p-4 border-t border-gray-700 text-xs text-gray-400">
          <p>GraphRAG v1.0.0</p>
        </div>
      )}
    </div>
  )
}

