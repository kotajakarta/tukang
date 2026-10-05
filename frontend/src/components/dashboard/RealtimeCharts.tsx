import React from 'react';
import { Card, Row, Col } from 'antd';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from 'recharts';
import { MetricDataPoint } from '../../types/metrics';
import { LineChartOutlined } from '@ant-design/icons';
import { useTheme } from '../../context/ThemeContext';

interface RealtimeChartsProps {
  history: MetricDataPoint[];
}

export const RealtimeCharts: React.FC<RealtimeChartsProps> = ({ history }) => {
  const { palette } = useTheme();
  const tooltipStyle = { backgroundColor: palette.surface, borderColor: palette.line, borderRadius: 6, color: palette.fg };
  return (
    <Row gutter={[16, 16]}>
      {/* CPU & Memory Chart */}
      <Col xs={24} lg={12}>
        <Card
          title={
            <div className="flex items-center gap-2">
              <LineChartOutlined className="text-accent" />
              <span>CPU & Memory History (%)</span>
            </div>
          }
          className="shadow-sm"
        >
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={history} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="cpuGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={palette.accent} stopOpacity={0.4} />
                    <stop offset="95%" stopColor={palette.accent} stopOpacity={0.0} />
                  </linearGradient>
                  <linearGradient id="memGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={palette.success} stopOpacity={0.4} />
                    <stop offset="95%" stopColor={palette.success} stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={palette["line-muted"]} />
                <XAxis dataKey="time" stroke={palette["fg-subtle"]} tick={{ fontSize: 11 }} />
                <YAxis domain={[0, 100]} stroke={palette["fg-subtle"]} tick={{ fontSize: 11 }} />
                <Tooltip
                  contentStyle={tooltipStyle}
                  itemStyle={{ fontSize: 12 }}
                />
                <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
                <Area
                  type="monotone"
                  dataKey="cpu"
                  name="CPU %"
                  stroke={palette.accent}
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#cpuGradient)"
                  isAnimationActive={false}
                />
                <Area
                  type="monotone"
                  dataKey="memory"
                  name="Memory %"
                  stroke={palette.success}
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#memGradient)"
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </Col>

      {/* Network Traffic Chart */}
      <Col xs={24} lg={12}>
        <Card
          title={
            <div className="flex items-center gap-2">
              <LineChartOutlined className="text-cyan" />
              <span>Network Traffic History (KB/s)</span>
            </div>
          }
          className="shadow-sm"
        >
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={history} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                <defs>
                  <linearGradient id="rxGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={palette.cyan} stopOpacity={0.4} />
                    <stop offset="95%" stopColor={palette.cyan} stopOpacity={0.0} />
                  </linearGradient>
                  <linearGradient id="txGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={palette.purple} stopOpacity={0.4} />
                    <stop offset="95%" stopColor={palette.purple} stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={palette["line-muted"]} />
                <XAxis dataKey="time" stroke={palette["fg-subtle"]} tick={{ fontSize: 11 }} />
                <YAxis stroke={palette["fg-subtle"]} tick={{ fontSize: 11 }} />
                <Tooltip
                  contentStyle={tooltipStyle}
                  itemStyle={{ fontSize: 12 }}
                />
                <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
                <Area
                  type="monotone"
                  dataKey="netRxKB"
                  name="Inbound RX (KB/s)"
                  stroke={palette.cyan}
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#rxGradient)"
                  isAnimationActive={false}
                />
                <Area
                  type="monotone"
                  dataKey="netTxKB"
                  name="Outbound TX (KB/s)"
                  stroke={palette.purple}
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#txGradient)"
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </Col>
    </Row>
  );
};
