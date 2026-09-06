#!/usr/bin/env python3
"""
Runner de consultas Supabase sin credenciales nuevas.

Uso:
    python tools/run_supabase_file.py <ruta_al_archivo_query>

El archivo query debe:
1. Estar commiteado en el repo (revisable en PR)
2. Definir una función run(client) que reciba el cliente de Supabase
3. Retornar un resultado serializable a JSON

El cliente se construye desde SUPABASE_URL y SUPABASE_KEY del entorno.
"""

import sys
import os
import json
import importlib.util

def main():
    if len(sys.argv) != 2:
        print(json.dumps({"error": "Uso: python run_supabase_file.py <ruta_al_archivo_query>"}))
        sys.exit(1)
    
    query_file = sys.argv[1]
    
    # Validar que el archivo existe
    if not os.path.isfile(query_file):
        print(json.dumps({"error": f"Archivo no encontrado: {query_file}"}))
        sys.exit(1)
    
    # Validar que el archivo está dentro del repo (seguridad)
    abs_path = os.path.abspath(query_file)
    repo_root = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    if not abs_path.startswith(repo_root):
        print(json.dumps({"error": f"El archivo debe estar dentro del repositorio: {query_file}"}))
        sys.exit(1)
    
    # Verificar credenciales
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    
    if not supabase_url or not supabase_key:
        print(json.dumps({
            "error": "Faltan credenciales de Supabase",
            "detalle": "Se requieren SUPABASE_URL y SUPABASE_KEY en el entorno"
        }))
        sys.exit(1)
    
    # Importar el módulo dinámicamente
    module_name = os.path.splitext(os.path.basename(query_file))[0]
    spec = importlib.util.spec_from_file_location(module_name, query_file)
    if spec is None or spec.loader is None:
        print(json.dumps({"error": f"No se pudo cargar el módulo: {query_file}"}))
        sys.exit(1)
    
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    
    # Verificar que existe la función run
    if not hasattr(module, "run"):
        print(json.dumps({
            "error": f"El archivo {query_file} debe definir una función run(client)"
        }))
        sys.exit(1)
    
    # Crear cliente de Supabase
    try:
        from supabase import create_client, Client
        client: Client = create_client(supabase_url, supabase_key)
    except ImportError:
        print(json.dumps({
            "error": "Paquete 'supabase' no instalado. Ejecutar: pip install supabase"
        }))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({
            "error": f"Error al crear cliente de Supabase: {str(e)}"
        }))
        sys.exit(1)
    
    # Ejecutar la consulta
    try:
        result = module.run(client)
        print(json.dumps({"success": True, "resultado": result}, default=str))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
