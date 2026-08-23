import os
import tempfile
import logging
import cadquery as cq

logger = logging.getLogger(__name__)


class GLTFExporter:
    @staticmethod
    def export(model: cq.Workplane, filename: str) -> str:
        """
        Exports a CadQuery model to a valid GLTF 2.0 file (JSON + buffers).

        Strategy:
          1. Export the CadQuery geometry to a temporary STL file.
          2. Load the STL into trimesh.
          3. Export as GLTF with proper buffer handling.

        Returns the path to the actual file created.
        """
        os.makedirs(os.path.dirname(filename), exist_ok=True)

        # ── Step 1: CadQuery → STL (always works) ──────────────────────────
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
            stl_path = tmp.name

        try:
            cq.exporters.export(model, stl_path)
            logger.debug("STL intermediate written to %s", stl_path)

            # ── Step 2: STL → GLTF via trimesh ────────────────────────────
            import trimesh
            from trimesh.exchange.gltf import export_gltf

            mesh = trimesh.load(stl_path, force="mesh")

            # Apply a neutral grey material
            mesh.visual = trimesh.visual.ColorVisuals(
                mesh=mesh,
                vertex_colors=[180, 180, 190, 255],  # RGBA
            )

            scene = trimesh.Scene(geometry={"model": mesh})

            # Export as GLTF with separate .bin buffers
            # This returns a dict: {filename: bytes_data}
            gltf_dict = export_gltf(scene)
            
            # Find the main .gltf file (the JSON)
            gltf_key = next(
                (k for k in gltf_dict if k.endswith(".gltf")),
                list(gltf_dict.keys())[0] if gltf_dict else None,
            )
            
            if not gltf_key:
                raise RuntimeError("No GLTF file generated from trimesh export")

            # Write the main GLTF JSON file
            with open(filename, "wb") as f:
                f.write(gltf_dict[gltf_key])
            logger.debug("GLTF JSON written: %s", filename)

            # Write companion .bin buffer files
            out_dir = os.path.dirname(filename)
            bin_count = 0
            for key, data in gltf_dict.items():
                if key == gltf_key or not isinstance(data, bytes):
                    continue
                companion_path = os.path.join(out_dir, key)
                with open(companion_path, "wb") as f:
                    f.write(data)
                logger.debug("Buffer file written: %s (size: %d bytes)", key, len(data))
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
                except:
                    pass


