import React, { createContext, useContext, useState, useEffect } from 'react';
import { ServerNode, ServerCreateInput } from '../types/server';
import { api } from '../services/api';
import { message } from 'antd';

interface ServerContextType {
  servers: ServerNode[];
  activeServer: ServerNode | null;
  loading: boolean;
  setActiveServerId: (id: string) => void;
  refreshServers: () => Promise<void>;
  addServer: (input: ServerCreateInput) => Promise<boolean>;
  updateServer: (id: string, input: Partial<ServerCreateInput>) => Promise<boolean>;
  removeServer: (id: string) => Promise<boolean>;
}

const ServerContext = createContext<ServerContextType | undefined>(undefined);

export const ServerProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [servers, setServers] = useState<ServerNode[]>([]);
  const [activeServer, setActiveServer] = useState<ServerNode | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const refreshServers = async () => {
    try {
      setLoading(true);
      const data = await api.getServers();
      setServers(data);
      if (data.length > 0) {
        if (!activeServer || !data.some(s => s.id === activeServer.id)) {
          // Default to local or first server
          const local = data.find(s => s.id === 'local') || data[0];
          setActiveServer(local);
        } else {
          // Update active server reference
          const current = data.find(s => s.id === activeServer.id);
          if (current) setActiveServer(current);
        }
      }
    } catch (err: any) {
      console.error('Failed to load servers:', err);
      message.error('Failed to fetch server inventory');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refreshServers();
  }, []);

  const setActiveServerId = (id: string) => {
    const found = servers.find(s => s.id === id);
    if (found) {
      setActiveServer(found);
      message.success(`Switched context to ${found.name}`);
    }
  };

  const addServer = async (input: ServerCreateInput): Promise<boolean> => {
    try {
      const created = await api.createServer(input);
      message.success(`Added server: ${created.name}`);
      await refreshServers();
      setActiveServer(created);
      return true;
    } catch (err: any) {
      message.error(err.response?.data?.detail || 'Failed to add server');
      return false;
    }
  };

  const updateServer = async (id: string, input: Partial<ServerCreateInput>): Promise<boolean> => {
    try {
      const updated = await api.updateServer(id, input);
      message.success(`Updated server: ${updated.name}`);
      await refreshServers();
      return true;
    } catch (err: any) {
      message.error(err.response?.data?.detail || 'Failed to update server');
      return false;
    }
  };

  const removeServer = async (id: string): Promise<boolean> => {
    try {
      await api.deleteServer(id);
      message.success('Server removed successfully');
      await refreshServers();
      return true;
    } catch (err: any) {
      message.error(err.response?.data?.detail || 'Failed to delete server');
      return false;
    }
  };

  return (
    <ServerContext.Provider
      value={{
        servers,
        activeServer,
        loading,
        setActiveServerId,
        refreshServers,
        addServer,
        updateServer,
        removeServer,
      }}
    >
      {children}
    </ServerContext.Provider>
  );
};

export const useServer = () => {
  const context = useContext(ServerContext);
  if (!context) {
    throw new Error('useServer must be used within a ServerProvider');
  }
  return context;
};
