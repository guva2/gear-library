/** Formats the API's 10-digit form as `(555) 123-4567`. */
export function formatPhoneNumber(digits: string): string {
  const match = /^([0-9]{3})([0-9]{3})([0-9]{4})$/.exec(digits);
  return match ? `(${match[1]}) ${match[2]}-${match[3]}` : digits;
}
