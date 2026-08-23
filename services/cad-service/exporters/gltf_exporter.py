import os
import tempfile
import logging
import json
import cadquery as cq

logger = logging.getLogger(__name__)


class GLTFExporter:
    @staticmethod
    def export(model: cq.Workplane, filename: str) -> str:
        """
        Exports a CadQuery model to a valid GLTF 2.0 file (JSON + buffers).

        Strategy:
          1. Export the CadQuery geometry to a temporary STL file.
          2. Load the STL into trimesh and validate geometry.
          3. Export as GLTF with deterministic buffer naming to avoid collisions.

        Returns the path to the actual file created.
        """
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        out_dir = os.path.dirname(filename)
        base_name = os.path.splitext(os.path.basename(filename))[0]

        # ── Step 1: CadQuery → STL (always works) ──────────────────────────
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
            stl_path = tmp.name

        try:
            cq.exporters.export(model, stl_path)
            logger.debug("STL intermediate written to %s", stl_path)

            # ── Step 2: STL → Mesh with validation ─────────────────────────
            import trimesh
            from trimesh.exchange.gltf import export_gltf

            mesh = trimesh.load(stl_path, force="mesh")
            
            # Validate mesh is not empty or degenerate
            if mesh.is_empty:
                raise RuntimeError("Mesh is empty after loading STL")
            if mesh.vertices.shape[0] < 3:
                raise RuntimeError("Mesh has fewer than 3 vertices (degenerate)")
            
            logger.debug("Mesh loaded: %d vertices, %d faces, volume=%.2f", 
                        mesh.vertices.shape[0], mesh.faces.shape[0], mesh.volume)

            # Apply a neutral grey material
            mesh.visual = trimesh.visual.ColorVisuals(
                mesh=mesh,
                vertex_colors=[180, 180, 190, 255],  # RGBA
            )

            scene = trimesh.Scene(geometry={"model": mesh})

            # ── Step 3: GLTF Export with deterministic buffer naming ────────
            gltf_dict = export_gltf(scene)
            
            if not gltf_dict:
                raise RuntimeError("GLTF export returned empty dict")

            # Find the main .gltf file (the JSON)
            gltf_key = next(
                (k for k in gltf_dict if k.endswith(".gltf")),
                None,
            )
            
            if not gltf_key:
                logger.error("Available GLTF keys: %s", list(gltf_dict.keys()))
                raise RuntimeError("No GLTF file generated from trimesh export")

            # ── Step 4: Write GLTF JSON and fix buffer URI references ──────
            gltf_json = gltf_dict[gltf_key]
            if isinstance(gltf_json, bytes):
                gltf_content = json.loads(gltf_json.decode('utf-8'))
            else:
                gltf_content = json.loads(gltf_json) if isinstance(gltf_json, str) else gltf_json

            # Rewrite buffer URIs to use deterministic names based on model ID
            buffer_mapping = {}  # {original_name: new_name}
            buffer_index = 0
            
            if "buffers" in gltf_content:
                for buf in gltf_content["buffers"]:
                    if "uri" in buf:
                        original_uri = buf["uri"]
                        # Use model-based deterministic naming
                        new_uri = f"{base_name}.buffer.{buffer_index}.bin"
                        buffer_mapping[original_uri] = new_uri
                        buf["uri"] = new_uri
                        logger.debug("Rewriting buffer URI: %s → %s", original_uri, new_uri)
                        buffer_index += 1

            # ── Step 5: Write GLTF JSON file ──────────────────────────────
            with open(filename, "w") as f:
                json.dump(gltf_content, f)
            logger.debug("GLTF JSON written: %s", filename)

            # ── Step 6: Write buffer files with deterministic names ────────
            bin_count = 0
            for key, data in gltf_dict.items():
                if key == gltf_key or not isinstance(data, bytes):
                    continue
                
                # Use the mapping we created for deterministic naming
                new_name = buffer_mapping.get(key, f"{base_name}.buffer.{bin_count}.bin")
                companion_path = os.path.join(out_dir, new_name)
                
                with open(companion_path, "wb") as f:
                    f.write(data)
                logger.debug("Buffer file written: %s (size: %d bytes)", new_name, len(data))
                bin_count += 1
            
            logger.info("GLTF 2.0 exported successfully: %s (+ %d buffers)", filename, bin_count)
            return filename

        except Exception as exc:
            logger.error("GLTF export failed: %s", exc, exc_info=True)
            # Fallback: return STL instead of broken GLTF
            stl_out = filename.replace(".gltf", ".stl")
            try:
                cq.exporters.export(model, stl_out)
                logger.warning("Fell back to STL export: %s", stl_out)
                return stl_out
            except Exception as stl_exc:
                logger.error("STL fallback also failed: %s", stl_exc)
                raise RuntimeError(f"Both GLTF and STL export failed: {exc}") from exc

        finally:
            # Always clean up the temp STL
            if os.path.exists(stl_path):
                try:
                    os.unlink(stl_path)
                except Exception as e:
                    logger.warning("Failed to clean up temp STL: %s", e)


