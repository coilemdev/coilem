# Third-Party Software Notices

This source snapshot does not vendor Python wheels, Rust crates, Node packages,
or compiled third-party binaries. `requirements.lock`,
`solvers/magneto2d/Cargo.lock`, and `frontend/package-lock.json` record the
audited dependency versions. Anyone distributing an installer or binary bundle
must also preserve the license files supplied by those packages and satisfy
their source-distribution obligations.

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
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| pillow | 12.3.0 | MIT-CMU |
| pydantic | 2.13.4 | MIT |
| pydantic-core | 2.46.4 | MIT |
| pygments | 2.20.0 | BSD-2-Clause |
| reportlab | 4.4.9 | BSD-3-Clause |
| referencing | 0.37.0 | MIT |
| rich | 15.0.0 | MIT |
| rpds-py | 0.30.0 | MIT |
| starlette | 1.3.1 | BSD-3-Clause |
| typing-extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.2 | MIT |
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

Vite 6.4.3, `@vitejs/plugin-react` 4.7.0, and their resolved build graph are
MIT-licensed development tools locked in `frontend/package-lock.json`.
TypeScript 5.6.3 is an Apache-2.0-licensed development tool. The build graph
also records esbuild, Rollup, PostCSS, Babel packages, source maps, filesystem
helpers, and platform-specific optional packages; these tools are not imported
as application runtime modules.

The browser regression suite uses `@playwright/test`, `playwright`, and
`playwright-core` 1.60.0 under Apache-2.0. Browser executables are installed
separately for testing and are not included in this source snapshot.
