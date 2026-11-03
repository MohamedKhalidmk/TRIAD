// The types of the VITE_ values of src/frontend/.env (import.meta.env).
// The build puts each VITE_ value into the JavaScript bundle, so each value is public.
// Never declare an API key or another secret here.

// With strictImportMetaEnv, "tsc -b" stops on a VITE_ name that is not declared below.
interface ViteTypeOptions {
  strictImportMetaEnv: unknown;
}

// The app uses no VITE_ value yet. Declare each new value here, for example:
//   readonly VITE_EXAMPLE: string;
interface ImportMetaEnv {}
