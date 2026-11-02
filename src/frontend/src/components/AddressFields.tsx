// The five address fields of the contract (Address). The form reads them with readAddress.

import { fieldError } from '../api/client';
import type { Address } from '../api/types';
import { formText, TextField } from './Field';

const PARTS: { name: keyof Address; label: string; autoComplete: string }[] = [
  { name: 'street', label: 'Street', autoComplete: 'street-address' },
  { name: 'city', label: 'City', autoComplete: 'address-level2' },
  { name: 'region', label: 'Region (state or province)', autoComplete: 'address-level1' },
  { name: 'postalCode', label: 'Postal code', autoComplete: 'postal-code' },
  { name: 'country', label: 'Country', autoComplete: 'country' },
];

export function AddressFields({ value, error, legend = 'Address' }: { value?: Address | null; error?: unknown; legend?: string }) {
  return (
    <fieldset className="fieldset">
      <legend>{legend}</legend>
      <div className="grid-2">
        {PARTS.map((part) => (
          <TextField
            key={part.name}
            name={`address.${part.name}`}
            label={part.label}
            defaultValue={value?.[part.name] ?? ''}
            autoComplete={part.autoComplete}
            error={fieldError(error, `address.${part.name}`, part.name)}
            className={part.name === 'street' ? 'span-2' : undefined}
          />
        ))}
      </div>
    </fieldset>
  );
}

export function readAddress(data: FormData): Address {
  return {
    street: formText(data, 'address.street'),
    city: formText(data, 'address.city'),
    region: formText(data, 'address.region'),
    postalCode: formText(data, 'address.postalCode'),
    country: formText(data, 'address.country'),
  };
}

export function formatAddress(address: Address | null | undefined): string {
  if (!address) return '';
  const cityLine = [address.city, address.region, address.postalCode].filter(Boolean).join(', ');
  return [address.street, cityLine, address.country].filter(Boolean).join(' · ');
}

export const ADDRESS_FIELD_NAMES = PARTS.map((part) => `address.${part.name}`);
