"use client";

import { useState, useEffect } from "react";

type ServiceStatus = "operational" | "degraded" | "outage" | "maintenance";

interface Service {
  id: string;
  name: string;
  status: ServiceStatus;
  uptime: string;
  lastIncident: string;
}

interface Incident {
  id: string;
  title: string;
  service: string;
  status: ServiceStatus;
  startedAt: string;
  resolvedAt?: string;
  description: string;
}

const statusConfig = {
  operational: {
    label: "Operational",
    bgColor: "bg-green-50",
    borderColor: "border-green-200",
    textColor: "text-green-700",
    barColor: "bg-green-400",
  },
  degraded: {
    label: "Degraded Performance",
    bgColor: "bg-amber-50",
    borderColor: "border-amber-200",
    textColor: "text-amber-700",
    barColor: "bg-amber-400",
  },
  outage: {
    label: "Major Outage",
    bgColor: "bg-red-50",
    borderColor: "border-red-200",
    textColor: "text-red-700",
    barColor: "bg-red-400",
  },
  maintenance: {
    label: "Maintenance",
    bgColor: "bg-blue-50",
    borderColor: "border-blue-200",
    textColor: "text-blue-700",
    barColor: "bg-blue-400",
  },
};

export default function StatusPage() {
  const [email, setEmail] = useState("");
  const [subscribed, setSubscribed] = useState(false);
  const [currentTime, setCurrentTime] = useState("");

  useEffect(() => {
    setCurrentTime(new Date().toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }));
  }, []);

  const services: Service[] = [
    { id: "1", name: "Web App", status: "operational", uptime: "99.98%", lastIncident: "45 days ago" },
    { id: "2", name: "API", status: "operational", uptime: "99.95%", lastIncident: "30 days ago" },
  ];

  const incidents: Incident[] = [
    {
      id: "1",
      title: "API Response Time Degradation",
      service: "API",
      status: "degraded",
      startedAt: "2026-07-15T14:30:00Z",
      resolvedAt: "2026-07-15T16:45:00Z",
      description: "Elevated response times affecting some API endpoints. Issue resolved.",
    },
    {
      id: "2",
      title: "Scheduled Maintenance Window",
      service: "Web App",
      status: "maintenance",
      startedAt: "2026-07-10T02:00:00Z",
      resolvedAt: "2026-07-10T04:00:00Z",
      description: "Routine infrastructure updates completed successfully.",
    },
    {
      id: "3",
      title: "Web App Brief Outage",
      service: "Web App",
      status: "outage",
      startedAt: "2026-06-28T09:15:00Z",
      resolvedAt: "2026-06-28T09:45:00Z",
      description: "Database connection issue resolved. All services restored.",
    },
  ];

  const getOverallStatus = (): ServiceStatus => {
    if (services.some((s) => s.status === "outage")) return "outage";
    if (services.some((s) => s.status === "degraded")) return "degraded";
    if (services.some((s) => s.status === "maintenance")) return "maintenance";
    return "operational";
  };

  const overallStatus = getOverallStatus();
  const overallConfig = statusConfig[overallStatus];

  const handleSubscribe = (e: React.FormEvent) => {
    e.preventDefault();
    if (email) {
      setSubscribed(true);
      setEmail("");
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  };

  return (
    <main className="min-h-screen bg-slate-50">
      <div className="max-w-4xl mx-auto px-6 py-12">
        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-4xl font-bold text-slate-900 mb-4">System Status</h1>
          <p className="text-slate-600">Real-time status and incident history for our services</p>
        </div>

        {/* Overall Status */}
        <div className={`rounded-xl border-2 ${overallConfig.borderColor} ${overallConfig.bgColor} p-8 mb-8`}>
          <div className="text-center">
            <p className={`text-2xl font-bold ${overallConfig.textColor}`}>
              All Systems {overallConfig.label}
            </p>
            <p className="text-slate-500 text-sm mt-2">Last updated: {currentTime}</p>
          </div>
        </div>

        {/* Service Status */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-8">
          <h2 className="text-xl font-semibold text-slate-900 mb-6">Service Status</h2>
          <div className="space-y-4">
            {services.map((service) => {
              const config = statusConfig[service.status];
              return (
                <div key={service.id} className="flex items-center justify-between p-4 rounded-lg bg-slate-50 border border-slate-100">
                  <span className="font-medium text-slate-900">{service.name}</span>
                  <div className="flex items-center gap-6 text-sm">
                    <span className="text-slate-500">Uptime: {service.uptime}</span>
                    <span className={`px-3 py-1 rounded-full text-xs font-medium ${config.bgColor} ${config.textColor}`}>
                      {config.label}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 90-Day Uptime */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-8">
          <h2 className="text-xl font-semibold text-slate-900 mb-4">90-Day Uptime</h2>
          <div className="flex gap-1 h-24 items-end">
            {Array.from({ length: 90 }).map((_, i) => {
              const dayStatus = i === 15 || i === 45 ? "degraded" : i === 30 ? "outage" : "operational";
              const height = dayStatus === "outage" ? "20%" : dayStatus === "degraded" ? "60%" : "100%";
              const color = statusConfig[dayStatus].barColor;
              return <div key={i} className={`flex-1 ${color} rounded-sm`} style={{ height }} />;
            })}
          </div>
          <div className="flex justify-between items-center mt-4 text-sm text-slate-500">
            <span>90 days ago</span>
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1"><span className="w-3 h-3 bg-green-400 rounded"></span> Operational</span>
              <span className="flex items-center gap-1"><span className="w-3 h-3 bg-amber-400 rounded"></span> Degraded</span>
              <span className="flex items-center gap-1"><span className="w-3 h-3 bg-red-400 rounded"></span> Outage</span>
            </div>
            <span>Today</span>
          </div>
        </div>

        {/* Incident History */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-8">
          <h2 className="text-xl font-semibold text-slate-900 mb-6">Recent Incidents (90 Days)</h2>
          <div className="space-y-4">
            {incidents.map((incident) => {
              const config = statusConfig[incident.status];
              const borderColors = { operational: "#22c55e", degraded: "#f59e0b", outage: "#ef4444", maintenance: "#3b82f6" };
              return (
                <div key={incident.id} className="border-l-4 pl-4 py-2" style={{ borderLeftColor: borderColors[incident.status] }}>
                  <div className="flex items-start justify-between">
                    <div>
                      <h3 className="font-medium text-slate-900">{incident.title}</h3>
                      <p className="text-sm text-slate-500 mt-1">{incident.description}</p>
                      <div className="flex items-center gap-4 mt-2 text-xs text-slate-400">
                        <span>{formatDate(incident.startedAt)}</span>
                        <span>Resolved: {incident.resolvedAt ? formatDate(incident.resolvedAt) : "Ongoing"}</span>
                      </div>
                    </div>
                    <span className={`px-2 py-1 rounded text-xs font-medium ${config.bgColor} ${config.textColor}`}>
                      {config.label}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Subscribe */}
        <div className="bg-slate-900 rounded-xl p-6 text-white">
          <h2 className="text-xl font-semibold mb-4">Subscribe to Updates</h2>
          <p className="text-slate-400 mb-4">Get notified instantly when we post an incident or update our status.</p>
          {subscribed ? (
            <p className="text-green-400">You have been subscribed successfully!</p>
          ) : (
            <form onSubmit={handleSubscribe} className="flex gap-3">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Enter your email"
                className="flex-1 px-4 py-3 rounded-lg bg-slate-800 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
                required
              />
              <button type="submit" className="px-6 py-3 bg-blue-500 hover:bg-blue-600 rounded-lg font-medium">Subscribe</button>
            </form>
          )}
        </div>

        <footer className="mt-12 pt-6 border-t border-slate-200 text-center text-sm text-slate-500">
          <p>© 2026 All rights reserved.</p>
        </footer>
      </div>
    </main>
  );
}