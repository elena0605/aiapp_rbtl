'use client'

import { useState } from 'react'
import ChatInterface from '@/components/ChatInterface'
import KnowledgeBase from '@/components/KnowledgeBase'
import Sidebar, { MenuOption } from '@/components/Sidebar'

export default function Home() {
  const [activeOption, setActiveOption] = useState<MenuOption>('chat')

  return (
    <main className="flex h-screen bg-gray-50 overflow-hidden">
      {/* Sidebar (1/4 of screen) */}
      <Sidebar activeOption={activeOption} onOptionChange={setActiveOption} />
      
      {/* Main Content Area (3/4 of screen) */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {activeOption === 'chat' && (
          <div className="flex-1 flex flex-col p-6 min-h-0 overflow-hidden">
            <div className="flex-1 min-h-0 overflow-hidden">
              <ChatInterface />
            </div>
          </div>
        )}
        
        {activeOption === 'knowledge-base' && (
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
            <KnowledgeBase />
          </div>
        )}
        
        {/* Future: Add other views here based on activeOption */}
        {activeOption !== 'chat' && activeOption !== 'knowledge-base' && (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-gray-500">Coming soon...</p>
          </div>
        )}
      </div>
    </main>
  )
}

