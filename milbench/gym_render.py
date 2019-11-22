"""
2D rendering framework from Gym. MIT license notice below.

Copyright (c) 2016 OpenAI (https://openai.com)

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import division
import os
import six
import sys

if "Apple" in sys.version:
    if 'DYLD_FALLBACK_LIBRARY_PATH' in os.environ:
        os.environ['DYLD_FALLBACK_LIBRARY_PATH'] += ':/usr/lib'
        # (JDS 2016/04/15): avoid bug on Anaconda 2.3.0 / Yosemite

try:
    import pyglet
except ImportError:
    raise ImportError('''
    Cannot import pyglet. HINT: you can install pyglet directly via 'pip
    install pyglet'. But if you really just want to install all Gym
    dependencies and not have to think about it, 'pip install -e .[all]' or
    'pip install gym[all]' will do it.
    ''')

try:
    from pyglet import gl
except ImportError:
    raise ImportError('''
    Error occurred while running `from pyglet.gl import *` HINT: make sure you
    have OpenGL install. On Ubuntu, you can run 'apt-get install
    python-opengl'. If you're running on a server, you may need a virtual frame
    buffer; something like this should work: 'xvfb-run -s \"-screen 0
    1400x900x24\" python <your_script.py>'
    ''')

import math  # noqa: E402
import numpy as np  # noqa: E402

RAD2DEG = 57.29577951308232


def get_display(spec):
    """Convert a display specification (such as :0) into an actual Display
    object.
    Pyglet only supports multiple Displays on Linux.
    """
    if spec is None:
        return None
    elif isinstance(spec, six.string_types):
        return pyglet.canvas.Display(spec)
    else:
        raise RuntimeError(
            'Invalid display spec: {}. (Must be string like :0 or None.)'.
            format(spec))


class Viewer(object):
    def __init__(self, width, height, visible, display=None, slave=False):
        display = get_display(display)

        self.width = width
        self.height = height
        self.window = pyglet.window.Window(width=width,
                                           height=height,
                                           display=display,
                                           visible=visible)
        self.window.on_close = self.window_closed_by_user
        self.isopen = True
        if not slave:
            self.reset_geoms()
            self.transform = Transform()

        gl.glEnable(gl.GL_BLEND)
        # tricks from OpenAI's multiagent particle env repo:
        # gl.glEnable(gl.GL_MULTISAMPLE)
        gl.glEnable(gl.GL_LINE_SMOOTH)
        # gl.glHint(gl.GL_LINE_SMOOTH_HINT, gl.GL_DONT_CARE)
        gl.glHint(gl.GL_LINE_SMOOTH_HINT, gl.GL_NICEST)
        gl.glLineWidth(2.0)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

    def reset_geoms(self):
        self.geoms = []
        self.onetime_geoms = []

    def close(self):
        self.window.close()

    def window_closed_by_user(self):
        self.isopen = False

    def set_bounds(self, left, right, bottom, top):
        assert right > left and top > bottom
        scalex = self.width / (right - left)
        scaley = self.height / (top - bottom)
        self.transform = Transform(translation=(-left * scalex,
                                                -bottom * scaley),
                                   scale=(scalex, scaley))

    def add_geom(self, geom):
        self.geoms.append(geom)

    def add_onetime(self, geom):
        self.onetime_geoms.append(geom)

    def render(self, return_rgb_array=False):
        gl.glClearColor(1, 1, 1, 1)
        self.window.clear()
        self.window.switch_to()
        self.window.dispatch_events()
        self.transform.enable()
        for geom in self.geoms:
            geom.render()
        for geom in self.onetime_geoms:
            geom.render()
        self.transform.disable()
        arr = None
        if return_rgb_array:
            buffer = pyglet.image.get_buffer_manager().get_color_buffer()
            image_data = buffer.get_image_data()
            arr = np.frombuffer(image_data.data, dtype=np.uint8)
            # In https://github.com/openai/gym-http-api/issues/2, we
            # discovered that someone using Xmonad on Arch was having
            # a window of size 598 x 398, though a 600 x 400 window
            # was requested. (Guess Xmonad was preserving a pixel for
            # the boundary.) So we use the buffer height/width rather
            # than the requested one.
            arr = arr.reshape(buffer.height, buffer.width, 4)
            arr = arr[::-1, :, 0:3]
        self.window.flip()
        self.onetime_geoms = []
        return arr if return_rgb_array else self.isopen

    # Convenience
    def draw_circle(self, radius=10, res=30, filled=True, **attrs):
        geom = make_circle(radius=radius, res=res, filled=filled)
        _add_attrs(geom, attrs)
        self.add_onetime(geom)
        return geom

    def draw_polygon(self, v, filled=True, **attrs):
        geom = make_polygon(v=v, filled=filled)
        _add_attrs(geom, attrs)
        self.add_onetime(geom)
        return geom

    def draw_polyline(self, v, **attrs):
        geom = make_polyline(v=v)
        _add_attrs(geom, attrs)
        self.add_onetime(geom)
        return geom

    def draw_line(self, start, end, **attrs):
        geom = Line(start, end)
        _add_attrs(geom, attrs)
        self.add_onetime(geom)
        return geom

    def get_array(self):
        self.window.flip()
        image_data = pyglet.image.get_buffer_manager().get_color_buffer(
        ).get_image_data()
        self.window.flip()
        arr = np.fromstring(image_data.data, dtype=np.uint8, sep='')
        arr = arr.reshape(self.height, self.width, 4)
        return arr[::-1, :, 0:3]

    def __del__(self):
        self.close()


class SlaveViewer(Viewer):
    """Offers another window on a different viewer."""
    def __init__(self, master_viewer, **kwargs):
        width = master_viewer.width
        height = master_viewer.height
        super().__init__(width=width, height=height, slave=True, **kwargs)
        self.master_viewer = master_viewer

    def reset_geoms(self):
        pass

    @property
    def geoms(self):
        return list(self.master_viewer.geoms)

    @geoms.setter
    def geoms(self, new_value):
        raise NotImplementedError()

    @property
    def onetime_geoms(self):
        return list(self.master_viewer.geoms)

    @onetime_geoms.setter
    def onetime_geoms(self, new_value):
        # this happens during render()
        pass

    @property
    def transform(self):
        return self.master_viewer.transform

    @transform.setter
    def transform(self, new_value):
        raise NotImplementedError()


def _add_attrs(geom, attrs):
    if "color" in attrs:
        geom.set_color(*attrs["color"])
    if "linewidth" in attrs:
        geom.set_linewidth(attrs["linewidth"])


class Geom(object):
    def __init__(self):
        self._color = Color((0, 0, 0, 1.0))
        self.attrs = [self._color]

    def render(self):
        for attr in reversed(self.attrs):
            attr.enable()
        self.render1()
        for attr in self.attrs:
            attr.disable()

    def render1(self):
        raise NotImplementedError

    def add_attr(self, attr):
        self.attrs.append(attr)
        return self

    def set_color(self, r, g, b):
        self._color.vec4 = (r, g, b, 1)
        return self


class Attr(object):
    def enable(self):
        raise NotImplementedError

    def disable(self):
        pass


class Transform(Attr):
    def __init__(self, translation=(0.0, 0.0), rotation=0.0, scale=(1, 1)):
        self.set_translation(*translation)
        self.set_rotation(rotation)
        self.set_scale(*scale)

    def enable(self):
        gl.glPushMatrix()
        # translate to GL loc ppint
        gl.glTranslatef(self.translation[0], self.translation[1], 0)
        gl.glRotatef(RAD2DEG * self.rotation, 0, 0, 1.0)
        gl.glScalef(self.scale[0], self.scale[1], 1)

    def disable(self):
        gl.glPopMatrix()

    def set_translation(self, newx, newy):
        self.translation = (float(newx), float(newy))
        return self

    def set_rotation(self, new):
        self.rotation = float(new)
        return self

    def set_scale(self, newx, newy):
        self.scale = (float(newx), float(newy))
        return self


class Color(Attr):
    def __init__(self, vec4):
        self.vec4 = vec4

    def enable(self):
        gl.glColor4f(*self.vec4)


class LineStyle(Attr):
    def __init__(self, style):
        self.style = style

    def enable(self):
        gl.glEnable(gl.GL_LINE_STIPPLE)
        gl.glLineStipple(1, self.style)

    def disable(self):
        gl.glDisable(gl.GL_LINE_STIPPLE)


class LineWidth(Attr):
    def __init__(self, stroke):
        self.stroke = stroke

    def enable(self):
        gl.glLineWidth(self.stroke)


class Point(Geom):
    def __init__(self):
        Geom.__init__(self)

    def render1(self):
        gl.glBegin(gl.GL_POINTS)  # draw point
        gl.glVertex3f(0.0, 0.0, 0.0)
        gl.glEnd()


class FilledPolygon(Geom):
    def __init__(self, v):
        Geom.__init__(self)
        self.v = v

    def render1(self):
        if len(self.v) == 4:
            gl.glBegin(gl.GL_QUADS)
        elif len(self.v) > 4:
            gl.glBegin(gl.GL_POLYGON)
        else:
            gl.glBegin(gl.GL_TRIANGLES)
        for p in self.v:
            gl.glVertex3f(p[0], p[1], 0)  # draw each vertex
        gl.glEnd()


def make_circle(radius=10, res=30, filled=True):
    points = []
    for i in range(res):
        ang = 2 * math.pi * i / res
        points.append((math.cos(ang) * radius, math.sin(ang) * radius))
    if filled:
        return FilledPolygon(points)
    else:
        return PolyLine(points, True)


def make_rect(width=10, height=10, filled=True):
    rad_h = height / 2
    rad_w = width / 2
    points = [(-rad_w, rad_h), (rad_w, rad_h), (rad_w, -rad_h),
              (-rad_w, -rad_h)]
    if filled:
        return FilledPolygon(points)
    else:
        return PolyLine(points, True)


def make_square(side_length=10, filled=True):
    return make_rect(side_length, side_length, filled)


def make_polygon(v, filled=True):
    if filled:
        return FilledPolygon(v)
    else:
        return PolyLine(v, True)


def make_polyline(v):
    return PolyLine(v, False)


def make_capsule(length, width):
    l, r, t, b = 0, length, width / 2, -width / 2
    box = make_polygon([(l, b), (l, t), (r, t), (r, b)])
    circ0 = make_circle(width / 2)
    circ1 = make_circle(width / 2)
    circ1.add_attr(Transform(translation=(length, 0)))
    geom = Compound([box, circ0, circ1])
    return geom


class Compound(Geom):
    def __init__(self, gs):
        Geom.__init__(self)
        self.gs = gs

    def render1(self):
        for g in self.gs:
            g.render()


class PolyLine(Geom):
    def __init__(self, v, close):
        Geom.__init__(self)
        self.v = v
        self.close = close
        self.linewidth = LineWidth(1)
        self.add_attr(self.linewidth)

    def render1(self):
        gl.glBegin(gl.GL_LINE_LOOP if self.close else gl.GL_LINE_STRIP)
        for p in self.v:
            gl.glVertex3f(p[0], p[1], 0)  # draw each vertex
        gl.glEnd()

    def set_linewidth(self, x):
        self.linewidth.stroke = x


class Line(Geom):
    def __init__(self, start=(0.0, 0.0), end=(0.0, 0.0)):
        Geom.__init__(self)
        self.start = start
        self.end = end
        self.linewidth = LineWidth(1)
        self.add_attr(self.linewidth)

    def render1(self):
        gl.glBegin(gl.GL_LINES)
        gl.glVertex2f(*self.start)
        gl.glVertex2f(*self.end)
        gl.glEnd()


class Image(Geom):
    def __init__(self, fname, width, height):
        Geom.__init__(self)
        self.width = width
        self.height = height
        img = pyglet.image.load(fname)
        self.img = img
        self.flip = False

    def render1(self):
        self.img.blit(-self.width / 2,
                      -self.height / 2,
                      width=self.width,
                      height=self.height)


# ================================================================


class SimpleImageViewer(object):
    def __init__(self, display=None, maxwidth=500):
        self.window = None
        self.isopen = False
        self.display = display
        self.maxwidth = maxwidth

    def imshow(self, arr):
        if self.window is None:
            height, width, _channels = arr.shape
            if width > self.maxwidth:
                scale = self.maxwidth / width
                width = int(scale * width)
                height = int(scale * height)
            self.window = pyglet.window.Window(width=width,
                                               height=height,
                                               display=self.display,
                                               vsync=False,
                                               resizable=True)
            self.width = width
            self.height = height
            self.isopen = True

            @self.window.event
            def on_resize(width, height):
                self.width = width
                self.height = height

            @self.window.event
            def on_close():
                self.isopen = False

        assert len(arr.shape
                   ) == 3, "You passed in an image with the wrong number shape"
        image = pyglet.image.ImageData(arr.shape[1],
                                       arr.shape[0],
                                       'RGB',
                                       arr.tobytes(),
                                       pitch=arr.shape[1] * -3)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER,
                           gl.GL_NEAREST)
        texture = image.get_texture()
        texture.width = self.width
        texture.height = self.height
        self.window.clear()
        self.window.switch_to()
        self.window.dispatch_events()
        texture.blit(0, 0)  # draw
        self.window.flip()

    def close(self):
        if self.isopen and sys.meta_path:
            # ^^^ check sys.meta_path to avoid 'ImportError: sys.meta_path is
            # None, Python is likely shutting down'
            self.window.close()
            self.isopen = False

    def __del__(self):
        self.close()
