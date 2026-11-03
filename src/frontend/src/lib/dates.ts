// Pure date helpers.
//
// The API sends times as ISO 8601 with an offset, for example "2026-10-30T09:01:00-04:00",
// and dates of birth as "YYYY-MM-DD". The hospital is in Eastern time.
// These helpers show a time as it is written in the string. They do not use new Date(),
// because new Date("1971-05-14") is midnight UTC, and the browser can show the day before.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const ISO_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?\s*(Z|[+-]\d{2}:?\d{2})?$/;

export interface DateParts {
  year: number;
  month: number; // 1 to 12
  day: number;
  hour: number | null;
  minute: number | null;
  offset: string | null;
}

/** Splits an ISO date or time string into its parts. Returns null if the string is not ISO 8601. */
export function parseIsoParts(value: string | null | undefined): DateParts | null {
  if (!value) return null;
  const match = ISO_PATTERN.exec(value.trim());
  if (!match) return null;
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  return {
    year: Number(match[1]),
    month,
    day,
    hour: match[4] === undefined ? null : Number(match[4]),
    minute: match[5] === undefined ? null : Number(match[5]),
    offset: match[7] ?? null,
  };
}

function pad2(value: number): string {
  return value < 10 ? `0${value}` : String(value);
}

/** "2026-10-30T09:01:00-04:00" gives "Oct 30, 2026". "1971-05-14" gives "May 14, 1971". */
export function formatDate(value: string | null | undefined): string {
  const parts = parseIsoParts(value);
  if (!parts) return value ?? '';
  return `${MONTHS[parts.month - 1]} ${parts.day}, ${parts.year}`;
}

/** "2026-10-30T09:01:00-04:00" gives "Oct 30, 2026 09:01". A date with no time gives the date only. */
export function formatDateTime(value: string | null | undefined): string {
  const parts = parseIsoParts(value);
  if (!parts) return value ?? '';
  const date = `${MONTHS[parts.month - 1]} ${parts.day}, ${parts.year}`;
  if (parts.hour === null || parts.minute === null) return date;
  return `${date} ${pad2(parts.hour)}:${pad2(parts.minute)}`;
}

/** "2026-10-30T09:01:00-04:00" gives "09:01". A date with no time gives "". */
export function formatTime(value: string | null | undefined): string {
  const parts = parseIsoParts(value);
  if (!parts || parts.hour === null || parts.minute === null) return '';
  return `${pad2(parts.hour)}:${pad2(parts.minute)}`;
}

/** "2019-06-12T10:00:00-04:00" gives "2019". */
export function formatYear(value: string | null | undefined): string {
  const parts = parseIsoParts(value);
  return parts ? String(parts.year) : value ?? '';
}

/** "2026-10-30T09:01:00-04:00" gives "2026-10-30". */
export function isoDatePart(value: string | null | undefined): string {
  const parts = parseIsoParts(value);
  if (!parts) return '';
  return `${parts.year}-${pad2(parts.month)}-${pad2(parts.day)}`;
}

/**
 * The time range of a visit or a location stay, for example
 * "Oct 30, 2026 09:01 to 11:15" (same day) or "Oct 30, 2026 09:01 to Oct 31, 2026 08:00".
 * An open range gives "Oct 30, 2026 09:01 to now".
 */
export function formatRange(start: string, end: string | null): string {
  const from = formatDateTime(start);
  if (!end) return `${from} to now`;
  if (isoDatePart(start) === isoDatePart(end) && formatTime(end)) return `${from} to ${formatTime(end)}`;
  return `${from} to ${formatDateTime(end)}`;
}

/** True if the string is a correct date of birth: "YYYY-MM-DD". */
export function isDateOnly(value: string): boolean {
  const parts = parseIsoParts(value);
  return parts !== null && parts.hour === null && /^\d{4}-\d{2}-\d{2}$/.test(value);
}
