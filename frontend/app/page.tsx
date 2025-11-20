'use client'

import { useEffect, useState } from 'react'
import ChatInterface from '@/components/ChatInterface'
import KnowledgeBase from '@/components/KnowledgeBase'
import FavoritesView from '@/components/FavoritesView'
import GraphInfo from '@/components/GraphInfo'
import Sidebar, { MenuOption } from '@/components/Sidebar'
import { fetchChatUsers } from '@/lib/api'

export default function Home() {
  const [activeOption, setActiveOption] = useState<MenuOption>('chat')
  const [testerUsers, setTesterUsers] = useState<string[]>([])
  const [selectedTester, setSelectedTester] = useState<string | null>(null)
  const [isLoadingTesters, setIsLoadingTesters] = useState(false)
  const [testerError, setTesterError] = useState<string | null>(null)
  const [isChatProcessing, setIsChatProcessing] = useState(false)

  useEffect(() => {
    const loadTesters = async () => {
      setIsLoadingTesters(true)
      setTesterError(null)
      try {
        const users = await fetchChatUsers()
        setTesterUsers(users)
        if (!selectedTester && users.length > 0) {
          setSelectedTester(users[0])
        }
      } catch (error) {
        setTesterError(
          `Unable to load tester accounts${
            error instanceof Error ? `: ${error.message}` : ''
          }`
        )
      } finally {
        setIsLoadingTesters(false)
      }
    }
    loadTesters()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <main className="flex h-screen bg-gray-50 overflow-hidden">
      {/* Sidebar (1/4 of screen) */}
      <Sidebar
        activeOption={activeOption}
        onOptionChange={setActiveOption}
        testerUsers={testerUsers}
        selectedTester={selectedTester}
        onTesterChange={setSelectedTester}
        isLoadingTesters={isLoadingTesters}
        testerError={testerError}
        isTesterSelectionDisabled={isChatProcessing}
      />
      
      {/* Main Content Area (3/4 of screen) */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {activeOption === 'chat' && (
          <div className="flex-1 flex flex-col p-6 min-h-0 overflow-hidden">
            <div className="flex-1 min-h-0 overflow-hidden">
              <ChatInterface
                selectedUser={selectedTester}
                isUserSelectionReady={!isLoadingTesters && !testerError}
                userLoadError={testerError}
                onProcessingChange={setIsChatProcessing}
              />
            </div>
          </div>
        )}
        
        {activeOption === 'knowledge-base' && (
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
            <KnowledgeBase selectedTester={selectedTester} />
          </div>
        )}

        {activeOption === 'favorites' && (
          <div className="flex-1 flex flex-col p-6 min-h-0 overflow-hidden">
            <FavoritesView
              selectedUser={selectedTester}
              isUserSelectionReady={!isLoadingTesters && !testerError}
            />
          </div>
        )}

        {activeOption === 'graph-info' && (
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
            <GraphInfo />
          </div>
        )}
        
        {/* Future: Add other views here based on activeOption */}
        {activeOption !== 'chat' &&
          activeOption !== 'knowledge-base' &&
          activeOption !== 'favorites' &&
          activeOption !== 'graph-info' && (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-gray-500">Coming soon...</p>
          </div>
        )}
      </div>
    </main>
  )
}

