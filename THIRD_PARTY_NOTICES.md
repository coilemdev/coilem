# Third-Party Software Notices

This source snapshot does not vendor Python wheels, Rust crates, Node packages,
or compiled third-party binaries. `requirements.lock`,
`solvers/magneto2d/Cargo.lock`, and `frontend/package-lock.json` record the
audited dependency versions. Anyone distributing an installer or binary bundle
must also preserve the license files supplied by those packages and satisfy
their source-distribution obligations.

coilEM release wheels bundle a compiled Magneto2D executable and the built
browser UI. They ship this file and `LICENSE` as license files. The license
files of the Rust crates linked into each wheel's executable are in
`backend/_licenses/magneto2d-rust-crates.txt`. The frontend runtime notices
below cover the bundled UI. Python dependencies are installed from their own
wheels, which carry their own license files.

## Modelica Standard Library M350-50A material model

`materials/electrical-steel/M350-50A.csv` is generated from the `M350_50A`
material parameters and `mu_rApprox` approximation function in the Modelica
Standard Library. The generator records the upstream source locations and fit
parameters. The relevant upstream source is distributed under this notice:

    BSD 3-Clause License

    Copyright (c) 1998-2025, Modelica Association and contributors
    All rights reserved.

    Redistribution and use in source and binary forms, with or without
    modification, are permitted provided that the following conditions are met:

    * Redistributions of source code must retain the above copyright notice,
      this list of conditions and the following disclaimer.

    * Redistributions in binary form must reproduce the above copyright notice,
      this list of conditions and the following disclaimer in the documentation
      and/or other materials provided with the distribution.

    * Neither the name of the copyright holder nor the names of its contributors
      may be used to endorse or promote products derived from this software
      without specific prior written permission.

    THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
    AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
    IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
    ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
    LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
    CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
    SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
    INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
    CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
    ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
    POSSIBILITY OF SUCH DAMAGE.

## Python runtime lock

| Package | Version | License expression |
| --- | ---: | --- |
| annotated-doc | 0.0.4 | MIT |
| annotated-types | 0.7.0 | MIT |
| anyio | 4.14.2 | MIT |
| attrs | 26.1.0 | MIT |
| charset-normalizer | 3.4.9 | MIT |
| click | 8.4.2 | BSD-3-Clause |
| colorama (Windows) | 0.4.6 | BSD-3-Clause |
| fastapi | 0.139.2 | MIT |
| gmsh | 4.15.2 | GPL-2.0-or-later with the Gmsh exception below |
| h11 | 0.16.0 | MIT |
| idna | 3.18 | BSD-3-Clause |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| markdown-it-py | 4.2.0 | MIT |
| mdurl | 0.1.2 | MIT |
| meshio | 5.3.5 | MIT |
| numpy (Python 3.11 to 3.14) | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| numpy (Python 3.15) | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| pillow | 12.3.0 | MIT-CMU |
| pydantic (Python 3.11 to 3.14) | 2.13.4 | MIT |
| pydantic (Python 3.15) | 2.14.1 | MIT |
| pydantic-core (Python 3.11 to 3.14) | 2.46.4 | MIT |
| pydantic-core (Python 3.15) | 2.50.1 | MIT |
| pygments | 2.20.0 | BSD-2-Clause |
| reportlab | 4.4.9 | BSD-3-Clause |
| referencing | 0.37.0 | MIT |
| rich | 15.0.0 | MIT |
| rpds-py (Python 3.11 to 3.14) | 0.30.0 | MIT |
| rpds-py (Python 3.15) | 2026.9.1 | MIT |
| starlette | 1.3.1 | BSD-3-Clause |
| typing-extensions | 4.16.0 | PSF-2.0 |
| typing-inspection (Python 3.11 to 3.14) | 0.4.2 | MIT |
| typing-inspection (Python 3.15) | 0.4.4 | MIT |
| uvicorn | 0.51.0 | BSD-3-Clause |

The licenses above are the package metadata shipped with the audited wheels.
NumPy's wheel contains additional component notices; a binary distributor must
retain NumPy's bundled `LICENSE.txt` in addition to this summary.
Pillow's wheel is distributed under its MIT-CMU license; binary distributors
must retain the license file shipped with Pillow.

## Rust direct dependencies

| Crate | Locked version | License expression |
| --- | ---: | --- |
| serde | 1.0.228 | MIT OR Apache-2.0 |
| serde_json | 1.0.149 | MIT OR Apache-2.0 |
| rayon | 1.12.0 | MIT OR Apache-2.0 |
| faer | 0.24.0 | MIT, with incorporated algorithm notices below |

`Cargo.lock` is the exact transitive crate inventory. Its resolved crates use
MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, Zlib, Unlicense, Unicode-3.0, or
compatible dual-license expressions. The lock also includes target-specific
Windows support crates even when building for another platform. No crate source
is copied into this repository.

Some MIT-licensed crates publish packages without their own license file:
faer 0.24.0 ships only the incorporated notices below, and faer-traits,
equator, equator-macro, nano-gemm with its c32, c64, core, f32 and f64 crates,
and pulp-wasm-simd-flag ship none. Their upstream LICENSE files are kept in
`tools/release/crate_notices/`, with their sources recorded in
`tools/release/rust_licenses.py`. Release wheels include them.

### faer incorporated algorithms

The faer 0.24.0 crate distributes four additional notice files:

- `COPYING.EIGEN.MPL2` for algorithms ported from Eigen under MPL-2.0;
- `COPYING.LAPACK.BSD` for algorithms ported from LAPACK under BSD-3-Clause;
- `COPYING.SUITE_SPARSE.AMD.BSD`; and
- `COPYING.SUITE_SPARSE.COLAMD.BSD`.

The SuiteSparse notices are reproduced verbatim below.

#### AMD

    AMD, Copyright (c), 1996-2022, Timothy A. Davis,
    Patrick R. Amestoy, and Iain S. Duff.  All Rights Reserved.

    Availability:

        http://www.suitesparse.com

    -------------------------------------------------------------------------------
    AMD License: BSD 3-clause:
    -------------------------------------------------------------------------------

        Redistribution and use in source and binary forms, with or without
        modification, are permitted provided that the following conditions are met:
            * Redistributions of source code must retain the above copyright
              notice, this list of conditions and the following disclaimer.
            * Redistributions in binary form must reproduce the above copyright
              notice, this list of conditions and the following disclaimer in the
              documentation and/or other materials provided with the distribution.
            * Neither the name of the organizations to which the authors are
              affiliated, nor the names of its contributors may be used to endorse
              or promote products derived from this software without specific prior
              written permission.

        THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
        AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
        IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
        ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDERS BE LIABLE FOR ANY
        DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
        (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
        LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
        ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
        (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
        SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

#### COLAMD

    COLAMD, Copyright 1998-2022, Timothy A. Davis.  http://www.suitesparse.com
    http://www.suitesparse.com

    --------------------------------------------------------------------------------

    COLAMD License: BSD 3-clause

        Redistribution and use in source and binary forms, with or without
        modification, are permitted provided that the following conditions are met:
            * Redistributions of source code must retain the above copyright
              notice, this list of conditions and the following disclaimer.
            * Redistributions in binary form must reproduce the above copyright
              notice, this list of conditions and the following disclaimer in the
              documentation and/or other materials provided with the distribution.
            * Neither the name of the organizations to which the authors are
              affiliated, nor the names of its contributors may be used to endorse
              or promote products derived from this software without specific prior
              written permission.

        THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
        AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
        IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
        ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDERS BE LIABLE FOR ANY
        DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
        (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
        LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
        ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
        (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
        SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

## Gmsh 4.15.2

Gmsh is copyright © 1997-2026 C. Geuzaine and J.-F. Remacle. It is
distributed under GPL version 2 or later with this exception, reproduced from
the Gmsh 4.15.2 reference manual:

    The copyright holders of Gmsh give you permission to combine Gmsh
    with code included in the standard release of Netgen (from Joachim
    Schöberl), METIS (from George Karypis at the University of
    Minnesota), OpenCASCADE (from Open CASCADE S.A.S) and ParaView
    (from Kitware, Inc.) under their respective licenses. You may copy
    and distribute such a system following the terms of the GNU GPL for
    Gmsh and the licenses of the other code concerned, provided that
    you include the source code of that other code when and as the GNU
    GPL requires distribution of source code.
    Note that people who make modified versions of Gmsh are not
    obligated to grant this special exception for their modified
    versions; it is their choice whether to do so. The GNU General
    Public License gives permission to release a modified version
    without this exception; this exception also makes it possible to
    release a modified version which carries forward this exception.

    End of exception.

Official license and source: [Gmsh 4.15.2 reference manual](https://gmsh.info/doc/texinfo/gmsh.html#License)
and [Gmsh downloads](https://gmsh.info/).

The repository declares Gmsh as an install-time dependency; it does not contain
the Gmsh wheel or shared library. A coilEM installer that redistributes Gmsh
must include Gmsh's complete GPL-2.0-or-later license and exception, preserve
its copyright and warranty notices, provide the corresponding source in a
GPL-compliant manner, and carry forward the licenses/source for any exception
libraries included in that Gmsh build.

## Elmer FEM 26.2 (optional external program)

This source snapshot contains a coilEM-owned adapter for Elmer, but it does not
contain, install, link, or redistribute Elmer executables, libraries, source,
or data. The adapter detects and invokes a separately installed `ElmerGrid`
and `ElmerSolver` through local files and subprocesses.

Elmer's upstream license policy states that the suite uses both GPL and LGPL.
It identifies the ElmerSolver main library, `matc`, and `fhutiter` as LGPL, and
identifies ElmerGrid, ElmerGUI, and most physical solver modules as GPL. The
exact license of every redistributed component must be checked against the
Elmer 26.2 source and license files.

Official sources: [Elmer license policy](https://github.com/ElmerCSC/elmerfem/blob/devel/license_texts/ElmerLicensePolicy.md)
and [Elmer FEM 26.2 release](https://github.com/ElmerCSC/elmerfem/releases/tag/release-26.2).

Anyone who distributes an installer or binary bundle containing Elmer must
include the applicable GPL/LGPL license texts and notices and satisfy the
corresponding-source and relinking obligations for the exact components they
ship. This notice records the current external-process boundary; it is not a
substitute for legal review of a future bundled or linked distribution.

## Frontend runtime

The browser application uses React 18.3.1, React DOM 18.3.1, and three.js
0.183.2. Their runtime dependency set is React, React DOM, Scheduler 0.23.2,
loose-envify 1.4.0, js-tokens 4.0.0, and three.js; all are MIT-licensed and locked in
`frontend/package-lock.json`.

React, React DOM, and Scheduler carry this notice:

    MIT License

    Copyright (c) Facebook, Inc. and its affiliates.

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

loose-envify is Copyright (c) 2015 Andres Suarez
<zertosh@gmail.com>. js-tokens is Copyright (c) 2014-2018 Simon Lydell. Both
are distributed under the same MIT terms reproduced above.

three.js carries this notice:

    The MIT License

    Copyright © 2010-2026 three.js authors

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in
    all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
    THE SOFTWARE.

## Frontend build tooling

Vite 6.4.4, `@vitejs/plugin-react` 4.7.0, and their resolved build graph are
MIT-licensed development tools locked in `frontend/package-lock.json`.
TypeScript 5.6.3 is an Apache-2.0-licensed development tool. The build graph
also records esbuild, Rollup, PostCSS, Babel packages, source maps, filesystem
helpers, and platform-specific optional packages; these tools are not imported
as application runtime modules.

The browser regression suite uses `@playwright/test`, `playwright`, and
`playwright-core` 1.60.0 under Apache-2.0. Browser executables are installed
separately for testing and are not included in this source snapshot.

## Pyleecan Prius reference data

The experimental Prius geometry, winding and steel data derive from
[Pyleecan's Toyota_Prius.json](https://github.com/Eomys/pyleecan/blob/cbfe7be3b8a50dbcdecccb655cc7ea74f2443890/pyleecan/Data/Machine/Toyota_Prius.json),
under Apache-2.0. Copyright 2018 EOMYS ENGINEERING, 2019-2020 Pyleecan developers.

coilEM changed the data representation: it exports analytic lines/arcs in mm,
rotates the drawing, partitions coincident shared edges and reflects it into
the app's clockwise frame. The shared IR preserves the analytic dimensions.
The bundled fixture also carries the published B-H samples and winding data.
Pyleecan and FEMM are optional research tools and are not runtime dependencies
of this fixture. The upstream license follows in full.

Adapted from Pyleecan reference data. No affiliation with or endorsement by
EOMYS, the Pyleecan project, or Toyota. The standalone Prius `.coilem` examples
and reference designs saved by the app include this attribution, a conversion
notice and the full Apache-2.0 license in their `reference_notice` metadata.

```
                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.

      "License" shall mean the terms and conditions for use, reproduction,
      and distribution as defined by Sections 1 through 9 of this document.

      "Licensor" shall mean the copyright owner or entity authorized by
      the copyright owner that is granting the License.

      "Legal Entity" shall mean the union of the acting entity and all
      other entities that control, are controlled by, or are under common
      control with that entity. For the purposes of this definition,
      "control" means (i) the power, direct or indirect, to cause the
      direction or management of such entity, whether by contract or
      otherwise, or (ii) ownership of fifty percent (50%) or more of the
      outstanding shares, or (iii) beneficial ownership of such entity.

      "You" (or "Your") shall mean an individual or Legal Entity
      exercising permissions granted by this License.

      "Source" form shall mean the preferred form for making modifications,
      including but not limited to software source code, documentation
      source, and configuration files.

      "Object" form shall mean any form resulting from mechanical
      transformation or translation of a Source form, including but
      not limited to compiled object code, generated documentation,
      and conversions to other media types.

      "Work" shall mean the work of authorship, whether in Source or
      Object form, made available under the License, as indicated by a
      copyright notice that is included in or attached to the work
      (an example is provided in the Appendix below).

      "Derivative Works" shall mean any work, whether in Source or Object
      form, that is based on (or derived from) the Work and for which the
      editorial revisions, annotations, elaborations, or other modifications
      represent, as a whole, an original work of authorship. For the purposes
      of this License, Derivative Works shall not include works that remain
      separable from, or merely link (or bind by name) to the interfaces of,
      the Work and Derivative Works thereof.

      "Contribution" shall mean any work of authorship, including
      the original version of the Work and any modifications or additions
      to that Work or Derivative Works thereof, that is intentionally
      submitted to Licensor for inclusion in the Work by the copyright owner
      or by an individual or Legal Entity authorized to submit on behalf of
      the copyright owner. For the purposes of this definition, "submitted"
      means any form of electronic, verbal, or written communication sent
      to the Licensor or its representatives, including but not limited to
      communication on electronic mailing lists, source code control systems,
      and issue tracking systems that are managed by, or on behalf of, the
      Licensor for the purpose of discussing and improving the Work, but
      excluding communication that is conspicuously marked or otherwise
      designated in writing by the copyright owner as "Not a Contribution."

      "Contributor" shall mean Licensor and any individual or Legal Entity
      on behalf of whom a Contribution has been received by Licensor and
      subsequently incorporated within the Work.

   2. Grant of Copyright License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      copyright license to reproduce, prepare Derivative Works of,
      publicly display, publicly perform, sublicense, and distribute the
      Work and such Derivative Works in Source or Object form.

   3. Grant of Patent License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      (except as stated in this section) patent license to make, have made,
      use, offer to sell, sell, import, and otherwise transfer the Work,
      where such license applies only to those patent claims licensable
      by such Contributor that are necessarily infringed by their
      Contribution(s) alone or by combination of their Contribution(s)
      with the Work to which such Contribution(s) was submitted. If You
      institute patent litigation against any entity (including a
      cross-claim or counterclaim in a lawsuit) alleging that the Work
      or a Contribution incorporated within the Work constitutes direct
      or contributory patent infringement, then any patent licenses
      granted to You under this License for that Work shall terminate
      as of the date such litigation is filed.

   4. Redistribution. You may reproduce and distribute copies of the
      Work or Derivative Works thereof in any medium, with or without
      modifications, and in Source or Object form, provided that You
      meet the following conditions:

      (a) You must give any other recipients of the Work or
          Derivative Works a copy of this License; and

      (b) You must cause any modified files to carry prominent notices
          stating that You changed the files; and

      (c) You must retain, in the Source form of any Derivative Works
          that You distribute, all copyright, patent, trademark, and
          attribution notices from the Source form of the Work,
          excluding those notices that do not pertain to any part of
          the Derivative Works; and

      (d) If the Work includes a "NOTICE" text file as part of its
          distribution, then any Derivative Works that You distribute must
          include a readable copy of the attribution notices contained
          within such NOTICE file, excluding those notices that do not
          pertain to any part of the Derivative Works, in at least one
          of the following places: within a NOTICE text file distributed
          as part of the Derivative Works; within the Source form or
          documentation, if provided along with the Derivative Works; or,
          within a display generated by the Derivative Works, if and
          wherever such third-party notices normally appear. The contents
          of the NOTICE file are for informational purposes only and
          do not modify the License. You may add Your own attribution
          notices within Derivative Works that You distribute, alongside
          or as an addendum to the NOTICE text from the Work, provided
          that such additional attribution notices cannot be construed
          as modifying the License.

      You may add Your own copyright statement to Your modifications and
      may provide additional or different license terms and conditions
      for use, reproduction, or distribution of Your modifications, or
      for any such Derivative Works as a whole, provided Your use,
      reproduction, and distribution of the Work otherwise complies with
      the conditions stated in this License.

   5. Submission of Contributions. Unless You explicitly state otherwise,
      any Contribution intentionally submitted for inclusion in the Work
      by You to the Licensor shall be under the terms and conditions of
      this License, without any additional terms or conditions.
      Notwithstanding the above, nothing herein shall supersede or modify
      the terms of any separate license agreement you may have executed
      with Licensor regarding such Contributions.

   6. Trademarks. This License does not grant permission to use the trade
      names, trademarks, service marks, or product names of the Licensor,
      except as required for reasonable and customary use in describing the
      origin of the Work and reproducing the content of the NOTICE file.

   7. Disclaimer of Warranty. Unless required by applicable law or
      agreed to in writing, Licensor provides the Work (and each
      Contributor provides its Contributions) on an "AS IS" BASIS,
      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
      implied, including, without limitation, any warranties or conditions
      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
      PARTICULAR PURPOSE. You are solely responsible for determining the
      appropriateness of using or redistributing the Work and assume any
      risks associated with Your exercise of permissions under this License.

   8. Limitation of Liability. In no event and under no legal theory,
      whether in tort (including negligence), contract, or otherwise,
      unless required by applicable law (such as deliberate and grossly
      negligent acts) or agreed to in writing, shall any Contributor be
      liable to You for damages, including any direct, indirect, special,
      incidental, or consequential damages of any character arising as a
      result of this License or out of the use or inability to use the
      Work (including but not limited to damages for loss of goodwill,
      work stoppage, computer failure or malfunction, or any and all
      other commercial damages or losses), even if such Contributor
      has been advised of the possibility of such damages.

   9. Accepting Warranty or Additional Liability. While redistributing
      the Work or Derivative Works thereof, You may choose to offer,
      and charge a fee for, acceptance of support, warranty, indemnity,
      or other liability obligations and/or rights consistent with this
      License. However, in accepting such obligations, You may act only
      on Your own behalf and on Your sole responsibility, not on behalf
      of any other Contributor, and only if You agree to indemnify,
      defend, and hold each Contributor harmless for any liability
      incurred by, or claims asserted against, such Contributor by reason
      of your accepting any such warranty or additional liability.

   END OF TERMS AND CONDITIONS

   APPENDIX: How to apply the Apache License to your work.

      To apply the Apache License to your work, attach the following
      boilerplate notice, with the fields enclosed by brackets "[]"
      replaced with your own identifying information. (Don't include
      the brackets!)  The text should be enclosed in the appropriate
      comment syntax for the file format. We also recommend that a
      file or class name and description of purpose be included on the
      same "printed page" as the copyright notice for easier
      identification within third-party archives.

   Copyright 2018 EOMYS ENGINEERING, 2019-2020 Pyleecan developers

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
```
