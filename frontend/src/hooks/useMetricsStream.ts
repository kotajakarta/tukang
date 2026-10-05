import { useState, useEffect, useRef } from 'react';
import { useServer } from '../context/ServerContext';
import { SystemMetricsPayload, MetricDataPoint } from '../types/metrics';
import { notifyUnauthorized, WS_UNAUTHORIZED } from '../services/api';

const MAX_HISTORY = 30;

export function useMetricsStream() {
  const { activeServer } = useServer();
  const [currentMetrics, setCurrentMetrics] = useState<SystemMetricsPayload | null>(null);
  const [history, setHistory] = useState<MetricDataPoint[]>([]);
  const [connected, setConnected] = useState<boolean>(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!activeServer) return;

    // Reset history and metrics on server change
    setHistory([]);
    setCurrentMetrics(null);

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/metrics`;

    let isSubscribed = true;
    let reconnectTimeout: any = null;

    const connect = () => {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isSubscribed) return;
        setConnected(true);
        // Subscribe to currently active server
        ws.send(JSON.stringify({ action: 'subscribe', server_id: activeServer.id }));
      };

      ws.onmessage = (event) => {
        if (!isSubscribed) return;
        try {
          const data: SystemMetricsPayload = JSON.parse(event.data);
          if (data.server_id === activeServer.id) {
            setCurrentMetrics(data);

            const timeStr = new Date(data.timestamp * 1000).toLocaleTimeString([], {
              hour12: false,
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
            });

            const point: MetricDataPoint = {
              time: timeStr,
              cpu: data.cpu.usage_percent,
              memory: data.memory.percent,
              diskReadMB: Math.round((data.disk_io.read_bytes_sec / (1024 * 1024)) * 10) / 10,
              diskWriteMB: Math.round((data.disk_io.write_bytes_sec / (1024 * 1024)) * 10) / 10,
              netRxKB: Math.round((data.network.rx_bytes_sec / 1024) * 10) / 10,
              netTxKB: Math.round((data.network.tx_bytes_sec / 1024) * 10) / 10,
            };

            setHistory((prev) => {
              const updated = [...prev, point];
              if (updated.length > MAX_HISTORY) {
                return updated.slice(updated.length - MAX_HISTORY);
              }
              return updated;
            });
          }
        } catch (e) {
          console.error('Error parsing metrics WS frame:', e);
        }
      };

      ws.onclose = (event) => {
        setConnected(false);
        if (event.code === WS_UNAUTHORIZED) {
          notifyUnauthorized();
          return;
        }
        if (isSubscribed) {
          reconnectTimeout = setTimeout(connect, 3000);
        }
      };

      ws.onerror = (err) => {
        console.warn('Metrics WS error:', err);
        ws.close();
      };
    };

    connect();

    return () => {
      isSubscribed = false;
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch (e) {}
      }
    };
  }, [activeServer?.id]);

  return { currentMetrics, history, connected };
}
