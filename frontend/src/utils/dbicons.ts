/** 数据库类型 → 图标与显示名(全应用统一)。 */
export const DB_META: Record<string, { icon: string; label: string }> = {
  pg: { icon: "🐘", label: "PostgreSQL" },
  mysql: { icon: "🐬", label: "MySQL" },
  mongo: { icon: "🍃", label: "MongoDB" },
  redis: { icon: "🧰", label: "Redis" },
  sqlite: { icon: "📦", label: "SQLite" },
}

export function dbMeta(type: string | null | undefined) {
  return DB_META[type ?? ""] ?? { icon: "❓", label: type ?? "未知" }
}
